"""
Benchmark script for PajGPS integration performance testing.

This script measures the time taken by each API call and provides statistics
about performance over multiple update cycles.

Usage:
    python benchmark.py [--iterations N] [--output FILE] [--delay SECONDS]

Examples:
    python benchmark.py                       # Run with default 5 iterations
    python benchmark.py --iterations 10       # Run 10 iterations
    python benchmark.py -o results.json       # Export results to JSON
    python benchmark.py -i 10 -o results.json # 10 iterations + export
    python benchmark.py -i 5 -d 2.0           # 5 iterations with 2 second delay
"""

import asyncio
import argparse
import json
import os
import sys
import time
from typing import Dict, List
from statistics import mean, median, stdev
from dotenv import load_dotenv

# Add parent directory to path to import pajgps_data
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import custom_components.pajgps.pajgps_data as pajgps_data


class BenchmarkMetrics:
    """Store timing metrics for a single operation."""

    def __init__(self, name: str):
        self.name = name
        self.times: List[float] = []

    def add_time(self, duration: float):
        """Add a timing measurement."""
        self.times.append(duration)

    def get_stats(self) -> Dict[str, float]:
        """Calculate statistics for collected times."""
        if not self.times:
            return {
                'count': 0,
                'min': 0.0,
                'max': 0.0,
                'avg': 0.0,
                'median': 0.0,
                'stdev': 0.0,
                'total': 0.0
            }

        return {
            'count': len(self.times),
            'min': min(self.times),
            'max': max(self.times),
            'avg': mean(self.times),
            'median': median(self.times),
            'stdev': stdev(self.times) if len(self.times) > 1 else 0.0,
            'total': sum(self.times)
        }


class PajGPSBenchmark:
    """Benchmark suite for PajGPS integration."""

    def __init__(self, iterations: int = 5, output_file: str = None, delay: float = 0.5):
        self.iterations = iterations
        self.output_file = output_file
        self.delay = delay
        self.metrics: Dict[str, BenchmarkMetrics] = {}
        self.data: pajgps_data.PajGPSData | None = None
        self.device_count = 0
        self.start_timestamp = None

    def _get_metric(self, name: str) -> BenchmarkMetrics:
        """Get or create a metric tracker."""
        if name not in self.metrics:
            self.metrics[name] = BenchmarkMetrics(name)
        return self.metrics[name]

    async def _timed_call(self, metric_name: str, coro):
        """Execute a coroutine and measure its execution time."""
        start_time = time.perf_counter()
        try:
            result = await coro
            duration = time.perf_counter() - start_time
            self._get_metric(metric_name).add_time(duration)
            return result, duration
        except Exception as e:
            duration = time.perf_counter() - start_time
            self._get_metric(f"{metric_name}_ERROR").add_time(duration)
            raise

    async def setup(self):
        """Initialize the PajGPS data instance."""
        load_dotenv()
        email = os.getenv('PAJGPS_EMAIL')
        password = os.getenv('PAJGPS_PASSWORD')

        if not email or not password:
            raise ValueError("PAJGPS_EMAIL and PAJGPS_PASSWORD must be set in .env file")

        print("Setting up benchmark...")
        await pajgps_data.PajGPSData.clean_instances()
        self.data = pajgps_data.PajGPSData.get_instance(
            "benchmark-guid",
            "benchmark",
            email,
            password,
            mark_alerts_as_read=False,  # Don't modify alerts during benchmark
            fetch_elevation=True,
            force_battery=True
        )
        delay_msg = f"{self.delay}s" if self.delay > 0 else "no delay"
        print(f"Benchmark initialized for {self.iterations} iterations (delay: {delay_msg})")
        print()

    async def cleanup(self):
        """Clean up resources."""
        if self.data:
            await self.data.async_close()
        await pajgps_data.PajGPSData.clean_instances()

    async def benchmark_login(self):
        """Benchmark login token retrieval."""
        _, duration = await self._timed_call(
            "login_get_token",
            self.data.get_login_token()
        )
        return duration

    async def run_single_iteration(self, iteration: int):
        """Run a single benchmark iteration."""
        print(f"Iteration {iteration + 1}/{self.iterations}:")
        print("-" * 60)

        # Login (only first iteration)
        if iteration == 0:
            duration = await self.benchmark_login()
            print(f"  ✓ Login token:          {duration * 1000:7.2f} ms")

        # Full update cycle with internal component timing
        start_full = time.perf_counter()

        # Refresh token
        start = time.perf_counter()
        await self.data.refresh_token(forced=True)
        duration = time.perf_counter() - start
        self._get_metric("refresh_token").add_time(duration)
        print(f"  ✓ Refresh token:        {duration * 1000:7.2f} ms")

        # Update devices
        start = time.perf_counter()
        await self.data.update_devices_data()
        duration = time.perf_counter() - start
        self._get_metric("update_devices").add_time(duration)
        device_count = len(self.data.devices)
        print(f"  ✓ Update devices:       {duration * 1000:7.2f} ms ({device_count} devices)")

        # Update positions
        start = time.perf_counter()
        await self.data.update_position_data()
        duration = time.perf_counter() - start
        self._get_metric("update_positions").add_time(duration)
        position_count = len(self.data.positions)
        print(f"  ✓ Update positions:     {duration * 1000:7.2f} ms ({position_count} positions)")

        # Update alerts
        start = time.perf_counter()
        await self.data.update_alerts_data()
        duration = time.perf_counter() - start
        self._get_metric("update_alerts").add_time(duration)
        alert_count = len(self.data.alerts)
        bg_tasks_count = len(self.data._background_tasks)
        print(f"  ✓ Update alerts:        {duration * 1000:7.2f} ms ({alert_count} alerts, {bg_tasks_count} bg tasks)")

        # Update sensors (may be slow, calls API per device)
        start = time.perf_counter()
        sensor_times = []
        headers = self.data.get_standard_headers()
        new_sensors = []

        for device in self.data.devices:
            device_start = time.perf_counter()
            url = f"https://connect.paj-gps.de/api/v1/sensordata/last/{device.id}"
            try:
                json = await self.data.make_get_request(url, headers)
                sensor_data = pajgps_data.PajGPSSensorData()
                if "success" in json and "volt" in json["success"]:
                    sensor_data.device_id = device.id
                    sensor_data.voltage = round(json["success"]["volt"] / 1000, 1)
                    new_sensors.append(sensor_data)
                else:
                    sensor_data.device_id = device.id
                    sensor_data.voltage = 0.0
                    new_sensors.append(sensor_data)
            except Exception as e:
                pass  # Error handling like in original

            device_duration = time.perf_counter() - device_start
            sensor_times.append((device.id, device_duration))

        self.data.sensors = new_sensors
        duration = time.perf_counter() - start
        self._get_metric("update_sensors").add_time(duration)
        sensor_count = len(self.data.sensors)

        # Show per-device times if any took >1s
        slow_sensors = [f"dev{did}:{t*1000:.0f}ms" for did, t in sensor_times if t > 1.0]
        if slow_sensors:
            print(f"  ✓ Update sensors:       {duration * 1000:7.2f} ms ({sensor_count} sensors) [SLOW: {', '.join(slow_sensors)}]")
        else:
            print(f"  ✓ Update sensors:       {duration * 1000:7.2f} ms ({sensor_count} sensors)")

        # Update elevation (single device)
        if self.data.fetch_elevation and device_count > 0:
            start = time.perf_counter()
            await self.data.update_elevation(self.data.get_device_ids()[0])
            duration = time.perf_counter() - start
            self._get_metric("update_elevation").add_time(duration)
            print(f"  ✓ Update elevation:     {duration * 1000:7.2f} ms (1 device)")

        # Calculate total time for full update
        full_duration = time.perf_counter() - start_full
        self._get_metric("full_update_measured").add_time(full_duration)
        print(f"  ✓ Full update (sum):    {full_duration * 1000:7.2f} ms")

        # Wait for background tasks to complete
        if self.data._background_tasks:
            start_time = time.perf_counter()
            await asyncio.gather(*self.data._background_tasks, return_exceptions=True)
            duration = time.perf_counter() - start_time
            self._get_metric("background_tasks_wait").add_time(duration)
            print(f"  ✓ Background tasks:     {duration * 1000:7.2f} ms")

        print()

    async def run(self):
        """Run the complete benchmark suite."""
        await self.setup()

        print("=" * 60)
        print("PAJGPS INTEGRATION PERFORMANCE BENCHMARK")
        print("=" * 60)
        print()

        self.start_timestamp = time.time()
        start_time = time.perf_counter()

        for i in range(self.iterations):
            await self.run_single_iteration(i)

            # Wait between iterations to avoid rate limiting
            if i < self.iterations - 1 and self.delay > 0:
                await asyncio.sleep(self.delay)

        total_time = time.perf_counter() - start_time

        # Store device count for export
        self.device_count = len(self.data.devices) if self.data else 0

        await self.cleanup()

        # Print summary
        self.print_summary(total_time)

        # Export results if requested
        if self.output_file:
            self.export_results(total_time)

    def print_summary(self, total_time: float):
        """Print benchmark summary statistics."""
        print("=" * 60)
        print("BENCHMARK SUMMARY")
        print("=" * 60)
        print()

        # Sort metrics by average time (descending)
        sorted_metrics = sorted(
            [(name, metric.get_stats()) for name, metric in self.metrics.items()],
            key=lambda x: x[1]['avg'],
            reverse=True
        )

        print(f"{'Operation':<25} {'Count':>5} {'Min':>8} {'Avg':>8} {'Max':>8} {'Median':>8} {'StdDev':>8} {'Total':>8}")
        print("-" * 110)

        for name, stats in sorted_metrics:
            if stats['count'] > 0:
                print(f"{name:<25} {stats['count']:>5} "
                      f"{stats['min']*1000:>7.1f}ms "
                      f"{stats['avg']*1000:>7.1f}ms "
                      f"{stats['max']*1000:>7.1f}ms "
                      f"{stats['median']*1000:>7.1f}ms "
                      f"{stats['stdev']*1000:>7.1f}ms "
                      f"{stats['total']*1000:>7.1f}ms")

        print("-" * 110)
        print(f"Total benchmark time: {total_time:.2f}s")
        print()

        # Performance insights
        # self.print_insights(sorted_metrics)

    def print_insights(self, sorted_metrics):
        """Print performance insights and recommendations."""
        print("=" * 60)
        print("PERFORMANCE INSIGHTS")
        print("=" * 60)
        print()

        # Find slowest operations
        slowest = [(name, stats) for name, stats in sorted_metrics if stats['count'] > 0][:3]

        if slowest:
            print("🔴 Slowest operations:")
            for name, stats in slowest:
                print(f"   • {name}: {stats['avg']*1000:.1f}ms average")
            print()

        # Check for high variance
        high_variance = [(name, stats) for name, stats in sorted_metrics
                        if stats['count'] > 1 and stats['stdev'] > stats['avg'] * 0.5]

        if high_variance:
            print("⚠️  High variance (inconsistent performance):")
            for name, stats in high_variance:
                print(f"   • {name}: {stats['stdev']*1000:.1f}ms standard deviation")
            print()

        # Sensor update warning
        sensor_stats = next((stats for name, stats in sorted_metrics if name == 'update_sensors'), None)
        if sensor_stats and sensor_stats['count'] > 0:
            devices_count = len(self.data.devices) if self.data else 0
            if devices_count > 0:
                avg_per_device = sensor_stats['avg'] / devices_count
                print(f"💡 Sensor updates:")
                print(f"   • {devices_count} devices")
                print(f"   • {sensor_stats['avg']*1000:.1f}ms total ({avg_per_device*1000:.1f}ms per device)")
                print(f"   • This makes {devices_count} sequential API calls")
                print()

        # Recommendations
        print("📋 Recommendations:")
        print("   • Consider caching data that doesn't change frequently")
        print("   • Monitor network latency to PAJ GPS servers")
        print("   • Adjust SCAN_INTERVAL based on your needs")
        print("   • Disable elevation updates if not needed (saves API calls)")
        print()

    def export_results(self, total_time: float):
        """Export benchmark results to JSON file."""
        results = {
            'timestamp': self.start_timestamp,
            'iterations': self.iterations,
            'delay_seconds': self.delay,
            'total_time_seconds': total_time,
            'device_count': self.device_count,
            'metrics': {}
        }

        for name, metric in self.metrics.items():
            stats = metric.get_stats()
            results['metrics'][name] = {
                'count': stats['count'],
                'min_ms': stats['min'] * 1000,
                'max_ms': stats['max'] * 1000,
                'avg_ms': stats['avg'] * 1000,
                'median_ms': stats['median'] * 1000,
                'stdev_ms': stats['stdev'] * 1000,
                'total_ms': stats['total'] * 1000,
                'all_times_ms': [t * 1000 for t in metric.times]
            }

        try:
            with open(self.output_file, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"✅ Results exported to: {self.output_file}")
            print()
        except Exception as e:
            print(f"❌ Failed to export results: {e}")
            print()


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Benchmark PajGPS Home Assistant integration performance',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          Run benchmark with 5 iterations (default)
  %(prog)s --iterations 10          Run benchmark with 10 iterations
  %(prog)s -i 3                     Run benchmark with 3 iterations
  %(prog)s -o results.json          Export results to JSON file
  %(prog)s -i 10 -o results.json    10 iterations + export to JSON
  %(prog)s -d 2.0                   Use 2 second delay between iterations
  %(prog)s -i 10 -d 1.5             10 iterations with 1.5 second delay
  %(prog)s -d 0                     No delay between iterations (faster but may hit rate limits)
        """
    )

    parser.add_argument(
        '-i', '--iterations',
        type=int,
        default=5,
        help='Number of iterations to run (default: 5)'
    )

    parser.add_argument(
        '-o', '--output',
        type=str,
        default=None,
        help='Output file for JSON results (optional)'
    )

    parser.add_argument(
        '-d', '--delay',
        type=float,
        default=0.5,
        help='Delay in seconds between iterations (default: 0.5, use 0 for no delay)'
    )

    return parser.parse_args()


async def main():
    """Main entry point."""
    args = parse_args()

    if args.iterations < 1:
        print("Error: iterations must be at least 1")
        sys.exit(1)

    if args.delay < 0:
        print("Error: delay must be 0 or greater")
        sys.exit(1)

    benchmark = PajGPSBenchmark(
        iterations=args.iterations,
        output_file=args.output,
        delay=args.delay
    )

    try:
        await benchmark.run()
    except KeyboardInterrupt:
        print("\n\nBenchmark interrupted by user")
        await benchmark.cleanup()
        sys.exit(1)
    except Exception as e:
        print(f"\n\nBenchmark failed: {e}")
        import traceback
        traceback.print_exc()
        await benchmark.cleanup()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())


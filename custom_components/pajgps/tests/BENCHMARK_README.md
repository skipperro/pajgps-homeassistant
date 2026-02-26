# PajGPS Integration Performance Benchmark

This benchmark tool measures the performance of the PajGPS Home Assistant integration by simulating real-world update cycles and timing each API call.

## Features

- 📊 Measures time for each API operation
- 📈 Provides min/max/avg/median/stdev statistics
- 🔄 Runs multiple iterations for accurate results
- 💾 Can export results to JSON for analysis
- 🎯 Identifies performance bottlenecks
- ⚡ Tracks background task execution

## Prerequisites

1. Python 3.10+ with asyncio support
2. Valid PajGPS credentials in `.env` file
3. Required dependencies installed (see `requirements.txt`)

## Setup

1. Create a `.env` file in the project root with your credentials:
```env
PAJGPS_EMAIL=your_email@example.com
PAJGPS_PASSWORD=your_password
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage

Run benchmark with default 5 iterations:
```bash
python benchmark.py
```

### Custom Number of Iterations

Run with 10 iterations for more accurate statistics:
```bash
python benchmark.py --iterations 10
```

Or use the short form:
```bash
python benchmark.py -i 10
```

### Export Results to JSON

Export results for further analysis:
```bash
python benchmark.py --output results.json
```

Or use the short form:
```bash
python benchmark.py -o results.json
```

### Combined Options

Run 10 iterations and export results:
```bash
python benchmark.py -i 10 -o results.json
```

## Output

### Console Output

The benchmark provides real-time feedback for each iteration:

```
Iteration 1/5:
------------------------------------------------------------
  ✓ Login token:          283.02 ms
  ✓ Refresh token:        238.12 ms
  ✓ Update devices:       124.63 ms (2 devices)
  ✓ Update positions:     216.86 ms (2 positions)
  ✓ Update alerts:        171.04 ms (0 alerts, 0 bg tasks)
  ✓ Update sensors:       190.50 ms (2 sensors)
  ✓ Update elevation:     142.22 ms (1 device)
  ✓ Full update cycle:    745.12 ms
```

After all iterations, it shows a summary with statistics:

```
============================================================
BENCHMARK SUMMARY
============================================================

Operation                 Count      Min      Avg      Max   Median   StdDev    Total
--------------------------------------------------------------------------------------------------------------
full_update                   5   704.0ms   714.6ms   726.1ms   713.7ms    11.1ms  3573.0ms
login_get_token               1   275.3ms   275.3ms   275.3ms   275.3ms     0.0ms   275.3ms
refresh_token                 5   210.9ms   235.4ms   251.2ms   244.1ms    21.5ms  1177.0ms
...
```

### Performance Insights

The benchmark automatically identifies:
- 🔴 **Slowest operations** - Operations taking the most time
- ⚠️ **High variance** - Operations with inconsistent performance
- 💡 **Optimization opportunities** - Suggestions for improvement

### JSON Export

When using `--output`, results are saved in JSON format:

```json
{
  "timestamp": 1705234567.123,
  "iterations": 5,
  "total_time_seconds": 6.38,
  "device_count": 2,
  "metrics": {
    "update_devices": {
      "count": 5,
      "min_ms": 112.9,
      "max_ms": 133.7,
      "avg_ms": 123.8,
      "median_ms": 124.8,
      "stdev_ms": 10.4,
      "total_ms": 619.0,
      "all_times_ms": [124.8, 112.9, 133.7, 120.5, 127.1]
    },
    ...
  }
}
```

## What is Measured

### Individual Operations

1. **Login token** - Initial authentication (measured once)
2. **Refresh token** - Token renewal
3. **Update devices** - Fetch device information
4. **Update positions** - Fetch GPS positions for all devices
5. **Update alerts** - Fetch active alerts/notifications
6. **Update sensors** - Fetch sensor data (voltage, etc.) - *One API call per device*
7. **Update elevation** - Fetch elevation from Open-Meteo API
8. **Background tasks** - Time spent waiting for async tasks (e.g., marking alerts as read)

### Combined Operations

- **Full update cycle** - Complete `async_update()` cycle as called by Home Assistant

## Understanding the Results

### Normal Performance

Typical times you might see:
- Login: 200-400ms (only happens once per session)
- Refresh token: 200-300ms
- Update devices: 100-200ms
- Update positions: 150-250ms
- Update alerts: 150-250ms
- Update sensors: 80-120ms per device
- Update elevation: 20-150ms per device
- Full update: 600-1000ms

### Performance Issues

Watch out for:
- **High average times** (>500ms for individual operations)
- **High standard deviation** (indicates network instability)
- **Sensor updates** taking >200ms per device
- **Full update** taking >2 seconds

### Factors Affecting Performance

- Network latency to PAJ GPS servers (Germany)
- Number of devices in your account
- Whether elevation updates are enabled
- Whether alerts need to be marked as read
- PAJ GPS server load
- Your internet connection speed

## Tips for Optimization

1. **Disable elevation updates** if you don't need altitude data
   - Saves one API call to Open-Meteo per device per update

2. **Adjust SCAN_INTERVAL** in configuration
   - Default is 30 seconds
   - Increase if you don't need frequent updates

3. **Monitor sensor updates**
   - Each device requires a separate API call
   - Consider if you really need voltage data

4. **Check network latency**
   - Run `ping connect.paj-gps.de` to check your connection
   - Consider your internet connection quality

## Troubleshooting

### "PAJGPS_EMAIL and PAJGPS_PASSWORD must be set"

Create a `.env` file in the project root with your credentials.

### "Password is incorrect" errors

Verify your credentials in the `.env` file are correct.

### Very slow performance

- Check your internet connection
- Try running at different times of day
- Consider if PAJ GPS servers are experiencing issues

### High variance in results

- Network instability
- Run more iterations for better average
- Check for other applications using your network

## License

This benchmark tool is part of the PajGPS Home Assistant integration.


"""Config flow for PAJ GPS Tracker integration."""
from __future__ import annotations
import logging
import uuid
from typing import Any, Dict, Optional
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from . import PajGPSData
from .const import DOMAIN

big_int = vol.All(vol.Coerce(int), vol.Range(min=300))
# Email validator that checks if the string is not empty and contains '@'
email_validator = vol.All(cv.string, vol.Length(min=1), vol.Match(r"^[^@]+@[^@]+\.[^@]+$"))

_LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = vol.Schema(
            {
                vol.Required('entry_name', default='My Paj GPS Account'): cv.string,
                vol.Required('email', default=''): cv.string,
                vol.Required('password', default=''): cv.string,
                vol.Required('mark_alerts_as_read', default=True): cv.boolean,
                vol.Required('fetch_elevation', default=False): cv.boolean,
                vol.Required('force_battery', default=False): cv.boolean,
            }
        )

class CustomFlow(config_entries.ConfigFlow, domain=DOMAIN):
    data: Optional[Dict[str, Any]]

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        errors: Dict[str, str] = {}
        if user_input is not None:
            self.data = user_input
            # Create new guid for the entry
            self.data['guid'] = str(uuid.uuid4())
            # If entry_name is null or empty string, add error
            if not self.data['entry_name'] or self.data['entry_name'] == '':
                errors['base'] = 'entry_name_required'
            # If email is null or empty string, add error
            if not self.data['email'] or self.data['email'] == '':
                errors['base'] = 'email_required'
            # If password is null or empty string, add error
            if not self.data['password'] or self.data['password'] == '':
                errors['base'] = 'password_required'
            if not errors:
                return self.async_create_entry(title=f"{self.data['entry_name']}", data=self.data)

        return self.async_show_form(step_id="user", data_schema=CONFIG_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)

class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handles options flow for the component."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        errors: Dict[str, str] = {}

        default_entry_name = ''
        if 'entry_name' in self.config_entry.data:
            default_entry_name = self.config_entry.data['entry_name']
        if 'entry_name' in self.config_entry.options:
            default_entry_name = self.config_entry.options['entry_name']
        default_email = ''
        if 'email' in self.config_entry.data:
            default_email = self.config_entry.data['email']
        if 'email' in self.config_entry.options:
            default_email = self.config_entry.options['email']
        default_password = ''
        if 'password' in self.config_entry.data:
            default_password = self.config_entry.data['password']
        if 'password' in self.config_entry.options:
            default_password = self.config_entry.options['password']
        default_mark_alerts_as_read = True
        if 'mark_alerts_as_read' in self.config_entry.data:
            default_mark_alerts_as_read = self.config_entry.data['mark_alerts_as_read']
        if 'mark_alerts_as_read' in self.config_entry.options:
            default_mark_alerts_as_read = self.config_entry.options['mark_alerts_as_read']
        default_fetch_elevation = False
        if 'fetch_elevation' in self.config_entry.data:
            default_fetch_elevation = self.config_entry.data['fetch_elevation']
        if 'fetch_elevation' in self.config_entry.options:
            default_fetch_elevation = self.config_entry.options['fetch_elevation']
        default_force_battery = False
        if 'force_battery' in self.config_entry.data:
            default_force_battery = self.config_entry.data['force_battery']
        if 'force_battery' in self.config_entry.options:
            default_force_battery = self.config_entry.options['force_battery']

        if user_input is not None:
            # If email is null or empty string, add error
            if not user_input['email'] or user_input['email'] == '':
                errors['base'] = 'email_required'
            # If password is null or empty string, add error
            if not user_input['password'] or user_input['password'] == '':
                errors['base'] = 'password_required'
            if not errors:
                # Update the config entry with the new data
                new_data = {
                    'guid': self.config_entry.data['guid'],
                    'entry_name': user_input['entry_name'],
                    'email': user_input['email'],
                    'password': user_input['password'],
                    'mark_alerts_as_read': user_input['mark_alerts_as_read'],
                    'fetch_elevation': user_input['fetch_elevation'],
                    'force_battery': user_input['force_battery'],
                }

                # Get existing instance of PajGPSData
                paj_data = PajGPSData.get_instance(
                    self.config_entry.data['guid'],
                    self.config_entry.data['entry_name'],
                    self.config_entry.data['email'],
                    self.config_entry.data['password'],
                    self.config_entry.data['mark_alerts_as_read'],
                    self.config_entry.data['fetch_elevation'],
                    self.config_entry.data['force_battery'],
                )
                paj_data.entry_name = new_data['entry_name']
                paj_data.email = new_data['email']
                paj_data.password = new_data['password']
                paj_data.mark_alerts_as_read = new_data['mark_alerts_as_read']
                paj_data.fetch_elevation = new_data['fetch_elevation']
                paj_data.force_battery = new_data['force_battery']

                self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

                await paj_data.refresh_token(True)
                await paj_data.async_update(True)

                # Rename the entry in the UI
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=new_data,
                    title=new_data['entry_name'],
                )

                return self.async_create_entry(title=f"{new_data['entry_name']}", data=new_data)



        OPTIONS_SCHEMA = vol.Schema(
            {
                vol.Required('entry_name', default=default_entry_name): cv.string,
                vol.Required('email', default=default_email): cv.string,
                vol.Required('password', default=default_password): cv.string,
                vol.Required('mark_alerts_as_read', default=default_mark_alerts_as_read): cv.boolean,
                vol.Required('fetch_elevation', default=default_fetch_elevation): cv.boolean,
                vol.Required('force_battery', default=default_force_battery): cv.boolean,
            }
        )
        return self.async_show_form(step_id="init", data_schema=OPTIONS_SCHEMA, errors=errors)

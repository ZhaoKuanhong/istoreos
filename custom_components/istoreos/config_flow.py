"""Configuration flow for the ubus integration."""

import asyncio

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .data_fetcher import AuthenticationError, DataFetcher, RouterError


class IStoreOSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Validate router access before creating the config entry."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()
            try:
                fetcher = DataFetcher(
                    user_input[CONF_HOST], user_input[CONF_USERNAME], user_input[CONF_PASSWORD],
                    session=async_get_clientsession(self.hass),
                )
                await fetcher.call("system", "info")
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except ValueError:
                errors["base"] = "invalid_host"
            except (aiohttp.ClientError, asyncio.TimeoutError, RouterError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="iStoreOS Router", data=user_input)

        return self.async_show_form(
            step_id="user", errors=errors,
            data_schema=vol.Schema({
                vol.Required(CONF_HOST, default=(user_input or {}).get(CONF_HOST, "192.168.1.1")): str,
                vol.Required(CONF_USERNAME, default=(user_input or {}).get(CONF_USERNAME, "root")): str,
                vol.Required(CONF_PASSWORD): str,
            }),
        )

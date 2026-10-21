from datetime import timedelta
import logging
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.const import CONF_HOST, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import ConfigEntryAuthFailed
from .data_fetcher import AuthenticationError, DataFetcher

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)

DOMAIN = "istoreos"
PLATFORMS = ["sensor", "button"]

async def async_setup(hass: HomeAssistant, config: dict):
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    host = entry.data[CONF_HOST]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    fetcher = DataFetcher(host, username, password, session=async_get_clientsession(hass))
    coordinator = iStoreOSDataUpdateCoordinator(hass, fetcher)
    await coordinator.async_config_entry_first_refresh()

    # ✅ 获取固件版本号并存入 hass.data
    try:
        version = await fetcher.get_firmware_version()
    except Exception as e:
        _LOGGER.warning("无法获取固件版本信息: %s", e)
        version = "未知版本"

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "fetcher": fetcher,
        "firmware_version": version,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["fetcher"].close()
    return unload_ok

class iStoreOSDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, fetcher: DataFetcher):
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self._fetcher = fetcher

    async def _async_update_data(self):
        try:
            data = await self._fetcher.fetch_status()
            if not data:
                raise UpdateFailed("Failed to fetch data from iStoreOS")
            return data
        except AuthenticationError as error:
            raise ConfigEntryAuthFailed(str(error)) from error
        except Exception as error:
            raise UpdateFailed(error) from error

"""Service adapters for ARR stack integration."""
from backend.adapters.base import ServiceAdapter, SourceService
from backend.adapters.sonarr import SonarrAdapter
from backend.adapters.radarr import RadarrAdapter
from backend.adapters.qbittorrent import QBittorrentAdapter
from backend.adapters.prowlarr import ProwlarrAdapter
from backend.adapters.guardarr import GuardarrAdapter


def get_adapter(service: SourceService) -> ServiceAdapter:
    """Get adapter for a given service."""
    adapters = {
        SourceService.SONARR: SonarrAdapter,
        SourceService.RADARR: RadarrAdapter,
        SourceService.QBITTORRENT: QBittorrentAdapter,
        SourceService.PROWLARR: ProwlarrAdapter,
        SourceService.GUARDARR: GuardarrAdapter,
    }

    adapter_class = adapters.get(service)
    if not adapter_class:
        raise ValueError(f"Unknown service: {service}")

    return adapter_class()


def get_all_adapters() -> list[ServiceAdapter]:
    """Get all configured adapters."""
    return [
        get_adapter(SourceService.SONARR),
        get_adapter(SourceService.RADARR),
        get_adapter(SourceService.QBITTORRENT),
        get_adapter(SourceService.PROWLARR),
        get_adapter(SourceService.GUARDARR),
    ]
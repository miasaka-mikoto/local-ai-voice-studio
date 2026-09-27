"""Engine and game-export adapter contracts for Local AI Voice Studio.

The package intentionally has no third-party runtime dependency.  Importing it
never starts an engine, probes a GPU, or reads credentials.
"""

from .base import (
    AdapterCancelled,
    AdapterError,
    AdapterUnavailable,
    EngineAdapter,
    EngineAdapterProtocol,
    ManifestOnlyEngineAdapter,
)
from .deployment import DeploymentImportResult, import_deployment_manifest
from .exporters import ExporterRegistry, export_game_manifest
from .game_manifest import GameLine, ManifestWriteError, export_lines, import_lines
from .mock_engine import MockEngineAdapter
from .models import (
    EngineCapability,
    EngineHealth,
    EngineKind,
    LicenseRisk,
    RuntimeWeight,
    SynthesisRequest,
    SynthesisResult,
)
from .naming import slug_component, stable_asset_name
from .registry import EngineRegistry
from .viseme import (
    DisabledVisemePlugin,
    VisemeCue,
    VisemePlugin,
    VisemeRegistry,
    VisemeResult,
)

__all__ = [
    "AdapterCancelled",
    "AdapterError",
    "AdapterUnavailable",
    "DeploymentImportResult",
    "DisabledVisemePlugin",
    "EngineAdapter",
    "EngineAdapterProtocol",
    "EngineCapability",
    "EngineHealth",
    "EngineKind",
    "EngineRegistry",
    "ExporterRegistry",
    "GameLine",
    "LicenseRisk",
    "ManifestWriteError",
    "ManifestOnlyEngineAdapter",
    "MockEngineAdapter",
    "RuntimeWeight",
    "SynthesisRequest",
    "SynthesisResult",
    "VisemeCue",
    "VisemePlugin",
    "VisemeRegistry",
    "VisemeResult",
    "export_game_manifest",
    "export_lines",
    "import_deployment_manifest",
    "import_lines",
    "slug_component",
    "stable_asset_name",
]

"""Module discovery, dependency validation and the model registry."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings
from .db import SCHEMAS
from .orm.model import BaseModel


class ModuleError(RuntimeError):
    pass


@dataclass(frozen=True)
class Manifest:
    name: str
    label: str
    schema: str
    version: str = "1.0"
    depends: tuple[str, ...] = ("base",)
    models: tuple[str, ...] = ()
    handlers: tuple[str, ...] = ()
    data: tuple[str, ...] = ()
    application: bool = False
    sequence: int = 100
    icon: str = ""
    summary: str = ""

    @classmethod
    def parse(cls, name: str, raw: dict[str, Any]) -> Manifest:
        manifest = cls(
            name=name,
            label=raw.get("name", name),
            schema=raw["schema"],
            version=raw.get("version", "1.0"),
            depends=tuple(raw.get("depends", ("base",))),
            models=tuple(raw.get("models", ())),
            handlers=tuple(raw.get("handlers", ())),
            data=tuple(raw.get("data", ())),
            application=bool(raw.get("application", False)),
            sequence=int(raw.get("sequence", 100)),
            icon=raw.get("web_icon", name),
            summary=raw.get("summary", ""),
        )
        if manifest.schema not in SCHEMAS:
            raise ModuleError(f"{name}: unknown schema {manifest.schema!r}")
        return manifest

    @property
    def path(self) -> Path:
        return Path(__file__).parent / "addons" / self.name


@dataclass
class Registry:
    settings: Settings
    modules: dict[str, Manifest] = field(default_factory=dict)
    models: dict[str, type[BaseModel]] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)

    # -- discovery ---------------------------------------------------------
    def discover(self) -> None:
        root = self.settings.addons_path
        if not root.is_dir():
            raise ModuleError(f"addons path does not exist: {root}")
        for entry in sorted(root.iterdir()):
            manifest_file = entry / "module.py"
            if not entry.is_dir() or not manifest_file.exists():
                continue
            module = importlib.import_module(f"kberp.addons.{entry.name}.module")
            raw = getattr(module, "MANIFEST", None)
            if not isinstance(raw, dict):
                raise ModuleError(f"{entry.name}/module.py has no MANIFEST dict")
            manifest = Manifest.parse(entry.name, raw)
            self.modules[manifest.name] = manifest
        if "base" not in self.modules:
            raise ModuleError("the base module is required")

    # -- dependency resolution --------------------------------------------
    def sort_modules(self) -> list[str]:
        missing = {
            dep
            for manifest in self.modules.values()
            for dep in manifest.depends
            if dep not in self.modules
        }
        if missing:
            raise ModuleError(f"missing module dependencies: {sorted(missing)}")

        ordered: list[str] = []
        state: dict[str, int] = {}

        def visit(name: str) -> None:
            mark = state.get(name, 0)
            if mark == 2:
                return
            if mark == 1:
                raise ModuleError(f"dependency cycle at {name!r}")
            state[name] = 1
            for dep in self.modules[name].depends:
                visit(dep)
            state[name] = 2
            ordered.append(name)

        for name in sorted(self.modules, key=lambda n: (self.modules[n].sequence, n)):
            visit(name)

        self.order = ordered
        return ordered

    # -- model registration ------------------------------------------------
    def load(self) -> None:
        self.discover()
        order = self.sort_modules()
        for name in order:
            manifest = self.modules[name]
            for model_path in manifest.models:
                importlib.import_module(model_path)
            for handler_path in manifest.handlers:
                importlib.import_module(handler_path)
        self._collect_models(order)

    def _collect_models(self, order: list[str]) -> None:
        seen: dict[str, type[BaseModel]] = {}
        for module_name in order:
            manifest = self.modules[module_name]
            prefix = f"kberp.addons.{module_name}."
            for subclass in _all_subclasses(BaseModel):
                if not getattr(subclass, "_name", ""):
                    continue
                if not subclass.__module__.startswith(prefix):
                    continue
                if subclass._name in seen and seen[subclass._name] is not subclass:
                    raise ModuleError(f"duplicate model {subclass._name}")
                if "_schema" not in subclass.__dict__ or subclass.__dict__["_schema"] is None:
                    subclass._schema = manifest.schema
                subclass._module = module_name
                seen[subclass._name] = subclass
        self.models = seen

    # -- lookups -----------------------------------------------------------
    def apps(self) -> list[Manifest]:
        return sorted(
            (m for m in self.modules.values() if m.application),
            key=lambda m: m.sequence,
        )

    def get(self, name: str) -> Manifest:
        return self.modules[name]


def _all_subclasses(cls: type[BaseModel]) -> set[type[BaseModel]]:
    found: set[type[BaseModel]] = set()
    for subclass in cls.__subclasses__():
        found.add(subclass)
        found |= _all_subclasses(subclass)
    return found

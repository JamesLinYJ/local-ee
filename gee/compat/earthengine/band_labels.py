"""Delay singleton band metadata until a cube process actually needs it.

Numeric callbacks, masks and source loads remain separate graph processes.
Only a pending band-dimension insertion or full singleton rename can absorb
another rename; materialization still uses the normal bounded node builder.
"""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class SingleBandReference:
    data: dict
    label: str
    add_dimension: bool


class BandLabels:
    def band_dimension(self, data, label):
        """A pending new bands dimension whose sole label can still change."""
        return SingleBandReference(data, label, True)

    def rename_band(self, data, label):
        """Rename a known singleton band, folding only pending metadata."""
        if isinstance(data, SingleBandReference):
            return replace(data, label=label)
        return SingleBandReference(data, label, False)

    def resolve_band_references(self, value):
        """Resolve internal references before serialization or node counting."""
        if isinstance(value, SingleBandReference):
            if value.add_dimension:
                return self.node("add_dimension", data=value.data,
                                 name="bands", label=value.label, type="bands")
            return self.node("rename_labels", data=value.data,
                             dimension="bands", target=[value.label])
        if isinstance(value, dict):
            return {key: self.resolve_band_references(child)
                    for key, child in value.items()}
        if isinstance(value, list):
            return [self.resolve_band_references(child) for child in value]
        if isinstance(value, tuple):
            return tuple(self.resolve_band_references(child) for child in value)
        return value

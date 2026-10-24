"""Local collection catalogue operations for decoded Earth Engine values."""
from __future__ import annotations

import math
from dataclasses import replace

from ...dem_contract import (
    COLLECTION_ID as DEM_COLLECTION_ID,
    DEMContractError,
    validate_dem_collection,
)
from .ir import (
    Collection,
    Image,
    ImageSequence,
    Pixel,
    Source,
    UnsupportedEEError,
    as_image,
    const,
    fail,
    rebind,
)


class CatalogOperations:
    """Materialize local assets and perform collection/image catalog queries."""

    def load(self, cid, image=False):
        alias = cid in {"COPERNICUS/S2_SR_HARMONIZED", "COPERNICUS/S2_SR"}
        original = cid
        if alias:
            cid = "sentinel-2-l2a"
            self.warn("Sentinel-2 alias uses only locally ingested, pre-cloud-masked reflectance converted to a DN view (x10000); limited coverage and bands B2/B3/B4/B8/SCL do not equal the full official Earth Engine dataset.")
        if cid not in self.catalog:
            fail(f"Collection is not locally ingested or verified: {original}")
        if cid == DEM_COLLECTION_ID:
            selected = self.items.get(cid, [])
            try:
                validate_dem_collection(
                    self.catalog[cid], selected, charge=self._charge_dem_metadata
                )
            except DEMContractError as exc:
                fail(
                    "Local DEM catalog metadata is legacy or invalid; resync/re-ingest "
                    f"cop-dem-glo-30 with the {DEM_COLLECTION_ID}/v1 contract ({exc})"
                )
        elif cid != "sentinel-2-l2a":
            fail(f"Collection has not passed Earth Engine compatibility acceptance: {cid}")
        metadata = self.catalog[cid]
        names = metadata.get("cube:dimensions", {}).get("bands", {}).get("values", [])
        if not names:
            fail("Local collection has no declared bands")
        selected = self.items.get(cid, [])
        source = Source(cid, tuple(i["id"] for i in selected), tuple(names), alias)
        mapping = {"blue": "B2", "green": "B3", "red": "B4", "nir": "B8", "SCL": "SCL"}
        bands = []
        for name in names:
            if alias and name not in mapping:
                continue
            pixel = Pixel("band", (source, name))
            if alias and name != "SCL":
                pixel = Pixel("multiply", (pixel, const(10000)))
            bands.append((mapping[name] if alias else name, pixel))
        result = Image(bands, {}, source)
        if image:
            if len(selected) != 1:
                fail("Image.load requires an unambiguous local image id; use ImageCollection.first()")
            result.props = dict(selected[0].get("properties", {}))
            if cid == DEM_COLLECTION_ID:
                result.props = self._base_properties(selected[0], cid)
            result.bands = [(name, Pixel("reduce_t", (pixel, "first"))) for name, pixel in result.bands]
            return result
        return Collection(source, result)

    def _charge_dem_metadata(self, count):
        if type(count) is not int or count < 0:
            fail("DEM metadata scan has an invalid work estimate")
        self.steps += count
        if self.steps > 50000:
            fail("DEM catalog metadata exceeds the shared 50000-step compilation work budget")

    def member(self, source, iid):
        return next(item for item in self.items[source.cid] if item["id"] == iid)

    def _base_properties(self, item, cid):
        original = item.get("properties", {})
        if cid != DEM_COLLECTION_ID:
            return dict(original)

        # Charge the shallow property copy and each string before scanning it.
        # Nested non-contract STAC values remain opaque and are not recursively
        # copied or treated as a security attestation by this schema.
        if type(original) is not dict or len(original) > 128:
            fail("DEM item properties are malformed or exceed 128 fields")
        self._charge_dem_metadata(len(original) + 1)
        for key, value in original.items():
            if type(key) is not str or len(key) > 4096:
                fail("DEM item property names must be bounded strings")
            self._charge_dem_metadata(len(key) + 1)
            if isinstance(value, str):
                if len(value) > 4096:
                    fail("DEM item property strings exceed the metadata string limit")
                self._charge_dem_metadata(len(value) + 1)
            else:
                self._charge_dem_metadata(1)

        from .date_values import millis

        properties = dict(original)
        timestamp = millis(original["datetime"])
        supplied_timestamp = original.get("system:time_start")
        if supplied_timestamp is not None:
            try:
                observed_timestamp = millis(supplied_timestamp)
            except (OverflowError, TypeError, ValueError):
                fail("DEM system:time_start must be a finite timestamp matching datetime")
            if not math.isclose(observed_timestamp, timestamp, rel_tol=0.0, abs_tol=0.001):
                fail("DEM system:time_start does not match its explicit datetime")
            # Keep an already-normalized numeric timestamp; convert an ISO value
            # to the numeric EE property expected by Image.get and Image.date.
            if isinstance(supplied_timestamp, (int, float)) and not isinstance(supplied_timestamp, bool):
                properties["system:time_start"] = supplied_timestamp
            else:
                properties["system:time_start"] = timestamp
        else:
            properties["system:time_start"] = timestamp
        source_id = properties["gee:source_id"]
        if "system:index" not in properties:
            properties["system:index"] = source_id
        elif (type(properties["system:index"]) is not str
              or not properties["system:index"].strip()
              or properties["system:index"] != source_id):
            fail("DEM system:index must match gee:source_id")
        return properties

    def properties(self, collection, iid):
        item = self.member(collection.source, iid)
        original = self._base_properties(item, collection.source.cid)
        image = collection.image
        props = dict(original) if image.inherit_props else {
            key: original[key] for key in image.copied_props if key in original
        }
        return {**props, **image.props}

    def collection_items(self, collection):
        items = [
            {
                **self.member(collection.source, iid),
                "properties": self.properties(collection, iid),
            }
            for iid in collection.source.ids
        ]
        if collection.image.footprint:
            from .geometry_consumers import reject_spherical_edges
            from .geometry_binary import invoke_geometry_binary
            from .geometry_preflight import _charge, measure_geometry
            from .geometry_topology import geometry_edge_models
            from .geometry_values import own_geometry_bounded
            from .spatial_filters import _own_catalog_geometry

            clip = own_geometry_bounded(self, collection.image.footprint)
            reject_spherical_edges(
                self, clip, "Collection footprint", default_geodesic=True,
            )
            cost = measure_geometry(clip)
            _charge(self, cost.nodes + cost.positions, "Collection footprint model inspection")
            if any(model is not False for model in geometry_edge_models(clip)):
                fail("Collection footprint does not support spherical geometry edges")
            items = [
                {**item, "geometry": invoke_geometry_binary(self, "Geometry.intersection", {
                    "left": _own_catalog_geometry(self, item["geometry"]),
                    "right": clip, "proj": "EPSG:4326",
                })}
                for item in items
            ]
        return items

    def footprint(self, value):
        from shapely.geometry import mapping, shape
        from shapely.ops import unary_union

        if isinstance(value, ImageSequence):
            geometries = [self.footprint(image) for image in value.images]
            default_geodesic = True
        elif isinstance(value, Collection):
            from .spatial_filters import _own_catalog_geometry

            # These rows are catalog-owned STAC footprints. Apply the legacy
            # planar default to raw catalog leaves before the shared consumer
            # guard, while retaining any typed child model sidecars.
            geometries = [
                _own_catalog_geometry(self, item["geometry"])
                for item in self.collection_items(value)
            ]
            default_geodesic = False
        elif isinstance(value, Image):
            if value.footprint is not None and value.footprint_is_absolute:
                return value.footprint
            if value.source is None:
                fail("Image geometry requires a source footprint")
            from .geometry_preflight import _charge, measure_geometry
            from .geometry_topology import geometry_edge_models
            from .geometry_values import own_geometry_bounded
            from .spatial_filters import _own_catalog_geometry

            geometries = [
                _own_catalog_geometry(
                    self, self.member(value.source, iid)["geometry"],
                )
                for iid in value.source.ids
            ]
            for geometry in geometries:
                cost = measure_geometry(geometry)
                _charge(self, cost.nodes + cost.positions, "Image.geometry model scan")
                if any(model is True for model in geometry_edge_models(geometry)):
                    fail("Image.geometry spherical geometry edges require a spherical raster/reprojection adapter")
            clip = None
            if value.footprint is not None:
                clip = own_geometry_bounded(self, value.footprint)
                from .geometry_consumers import reject_spherical_edges

                reject_spherical_edges(
                    self, clip, "Image.geometry clip", default_geodesic=True,
                )
                cost = measure_geometry(clip)
                _charge(self, cost.nodes + cost.positions, "Image.geometry clip model scan")
                if any(model is True for model in geometry_edge_models(clip)):
                    fail("Image.geometry spherical geometry edges require a spherical raster/reprojection adapter")
            base = unary_union([shape(geometry) for geometry in geometries])
            result = mapping(base.intersection(shape(clip)) if clip else base)
            kind = result.get("type")
            if kind in {"LineString", "LinearRing", "MultiLineString", "Polygon",
                        "MultiPolygon", "GeometryCollection"}:
                # This branch used only explicitly planar catalog/clip edges
                # with GEOS. Keep that model visible to downstream EE geometry
                # consumers instead of returning an unflagged spherical value.
                result["geodesic"] = False
                if kind in {"Polygon", "MultiPolygon"}:
                    result["evenOdd"] = True
            return result
        elif isinstance(value, dict) and value.get("type") == "Feature":
            return value["geometry"]
        elif isinstance(value, dict) and value.get("type") == "FeatureCollection":
            geometries = [feature["geometry"] for feature in value["features"] if feature.get("geometry")]
            default_geodesic = True
        else:
            fail("Geometry requires an Image, Collection or Feature")
        if not geometries:
            fail("An empty collection has no footprint")
        from .geometry_consumers import reject_spherical_edges

        for geometry in geometries:
            reject_spherical_edges(
                self, geometry, "Collection.geometry",
                default_geodesic=default_geodesic,
            )
        result = mapping(unary_union([shape(geometry) for geometry in geometries]))
        from .geometry_topology import _has_edges

        if _has_edges(result):
            result["geodesic"] = False
        return result

    def select(self, image, selectors, names=None):
        if isinstance(image, ImageSequence):
            return ImageSequence([self.select(item, selectors, names) for item in image.images])
        if isinstance(image, Collection):
            return replace(image, image=self.select(image.image, selectors, names))
        image = as_image(image)
        from .array_core import charge_array

        if type(image.bands) is not list or len(image.bands) > 10_000:
            fail("Image.select supports at most10000 input bands")
        selectors = selectors if isinstance(selectors, list) else [selectors]
        if len(selectors) > 10_000:
            fail("Image.select supports at most10000 selectors")
        charge_array(self, len(selectors) + 1)
        has_string_selector = any(isinstance(selector, str) for selector in selectors)
        if has_string_selector:
            charge_array(self, len(image.bands) + 1)
            for band in image.bands:
                if (type(band) is not tuple or len(band) != 2
                        or type(band[0]) is not str):
                    fail("Image.select requires named Pixel bands")

        # Exact selector work depends on the candidate's length.  Comparing a
        # long selector to a differently sized band name is an O(1) length
        # check, so do not charge or scan every band name just to find that
        # out.  Reserve all comparisons before performing any equality test.
        selection_work = 0
        for selector in selectors:
            if isinstance(selector, str):
                selection_work += len(image.bands) + 1
                selection_work += sum(
                    len(selector) for name, _ in image.bands
                    if len(name) == len(selector)
                )
            elif isinstance(selector, int) and not isinstance(selector, bool):
                selection_work += 1
            else:
                fail("Band selectors must be strings or zero-based integer indices")
        charge_array(self, selection_work)

        output = []
        for selector in selectors:
            if isinstance(selector, int) and not isinstance(selector, bool):
                if selector < 0 or selector >= len(image.bands):
                    fail(f"Band index out of range: {selector}")
                matched = [image.bands[selector]]
            elif isinstance(selector, str):
                matched = [
                    band for band in image.bands
                    if len(band[0]) == len(selector) and band[0] == selector
                ]
                if not matched:
                    from .regex_values import compile_pattern

                    # Pay for the bounded subject-list copy before allocating it;
                    # compile_pattern separately charges UTF-8 and RE2 scan work.
                    charge_array(self, len(image.bands) + 1)
                    try:
                        pattern = compile_pattern(
                            self, selector, tuple(name for name, _ in image.bands),
                        )
                    except UnsupportedEEError as exc:
                        # Keep the existing selector-facing diagnostic for
                        # unsupported RE2 syntax while allowing all shared
                        # work and size-budget failures to propagate intact.
                        if ("Regular expression is invalid or uses syntax unsupported by RE2"
                                in str(exc)):
                            fail(f"Invalid band selector: {selector}")
                        raise
                    matched = [
                        band for band in image.bands
                        if pattern.fullmatch(band[0])
                    ]
                if not matched:
                    from .array_core import charge_array

                    charge_array(self, len(image.bands) + 1)
                    charge_array(self, sum(len(name) + 1 for name, _ in image.bands))
                    available = [name for name, _ in image.bands]
                    fail(f"Band selector {selector!r} did not match; available: {available}")
            else:
                # Non-string selector types were rejected in the preflight.
                fail("Band selectors must be strings or zero-based integer indices")
            if len(output) + len(matched) > 10_000:
                fail("Image.select exceeds10000 output bands")
            output.extend(matched)
        charge_array(self, len(output) + 1)
        output_name_work = sum(len(name) + 1 for name, _ in output)
        charge_array(self, output_name_work)
        output_names = [name for name, _ in output]
        if len(set(output_names)) != len(output):
            fail("Repeated selected bands are not supported")
        if names is not None:
            if not isinstance(names, list) or len(names) != len(output):
                fail("New band names must be distinct strings matching the band count")
            charge_array(self, len(names) + 1)
            if any(not isinstance(name, str) for name in names):
                fail("New band names must be distinct strings matching the band count")
            charge_array(self, sum(len(name) + 1 for name in names))
            if len(set(names)) != len(names):
                fail("New band names must be distinct strings matching the band count")
            output = [(name, pixel) for name, (_, pixel) in zip(names, output)]
        # The pinned EE clients serialize select([]) as an ordinary empty
        # bandSelectors list.  Keep the Image envelope (including its source,
        # footprint and properties) while dropping every selected Pixel DAG;
        # downstream raster consumers decide whether their operation accepts
        # a zero-band image.
        if not output:
            from .owned_metadata_values import owned_metadata_copy

            props = owned_metadata_copy(self, image.props, "Image.select properties")
            if image.footprint is None:
                footprint = None
            else:
                from .spatial_filters import _own_catalog_geometry

                footprint = _own_catalog_geometry(self, image.footprint)
            return replace(image, bands=output, props=props, footprint=footprint)
        return replace(image, bands=output)

    def first(self, collection):
        if not collection.source.ids:
            fail("Cannot take first image of an empty collection")
        selected = rebind(collection, collection.source.ids[:1])
        props = self.properties(selected, selected.source.ids[0])
        return replace(
            selected.image,
            props=props,
            bands=[(name, Pixel("reduce_t", (pixel, "first"))) for name, pixel in selected.image.bands],
        )

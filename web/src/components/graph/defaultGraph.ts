import type { ProcessGraph } from "../../types";

export const initialGraph: ProcessGraph = {
  load: {
    process_id: "load_collection",
    arguments: {
      id: "sentinel-2-l2a",
      spatial_extent: { west: 113.55, south: 22.3, east: 113.57, north: 22.32 },
      temporal_extent: ["2024-01-19", "2024-01-20"],
      bands: ["red", "nir"],
    },
  },
  ndvi: {
    process_id: "ndvi",
    arguments: { data: { from_node: "load" }, nir: "nir", red: "red" },
  },
  mean: {
    process_id: "reduce_dimension",
    arguments: {
      data: { from_node: "ndvi" },
      dimension: "t",
      reducer: {
        process_graph: {
          mean: {
            process_id: "mean",
            arguments: { data: { from_parameter: "data" } },
            result: true,
          },
        },
      },
    },
  },
  save: {
    process_id: "save_result",
    arguments: { data: { from_node: "mean" }, format: "GTiff" },
    result: true,
  },
};

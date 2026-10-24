#include "s2_internal.h"

#include <algorithm>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include "s2/s2debug.h"
#include "s2/s2loop.h"

namespace local_ee_s2 {
namespace {

using UndirectedEdge = std::pair<PointKey, PointKey>;

struct EdgeReference {
  size_t loop_index;
  size_t edge_index;
};

struct EdgeGroup {
  std::vector<EdgeReference> forward;
  std::vector<EdgeReference> reverse;
};

struct LoopData {
  std::vector<S2Point> vertices;
  std::vector<bool> remove_edge;
};

bool Fail(std::string* error, const std::string& message) {
  *error = message;
  return false;
}

UndirectedEdge MakeUndirectedEdge(const S2Point& a, const S2Point& b) {
  PointKey a_key = KeyForPoint(a);
  PointKey b_key = KeyForPoint(b);
  if (b_key < a_key) std::swap(a_key, b_key);
  return {a_key, b_key};
}

void AddUniquePoint(const S2Point& point, std::set<PointKey>* keys,
                    GeometryOutput* output) {
  if (keys->insert(KeyForPoint(point)).second) output->points.push_back(point);
}

bool AddUniqueLine(const S2Point& a, const S2Point& b,
                   std::set<UndirectedEdge>* keys, GeometryOutput* output,
                   std::string* error) {
  if (a == b) {
    *error = "polygon degeneracy unexpectedly contains a zero-length line";
    return false;
  }
  if (!keys->insert(MakeUndirectedEdge(a, b)).second) return true;
  std::vector<S2Point> vertices{a, b};
  auto line = std::make_unique<S2Polyline>(vertices, S2Debug::DISABLE);
  S2Error line_error;
  if (line->FindValidationError(&line_error)) {
    *error = std::string("invalid degenerate polygon boundary: ") +
             std::string(line_error.message());
    return false;
  }
  output->polylines.push_back(std::move(line));
  return true;
}

}  // namespace

bool ExtractLaxPolygon(const S2LaxPolygonShape& lax_polygon,
                       GeometryOutput* output, std::string* error) {
  if (output == nullptr || error == nullptr) {
    return Fail(error, "lax polygon output state is null");
  }

  std::set<PointKey> point_keys;
  for (const S2Point& point : output->points) point_keys.insert(KeyForPoint(point));
  std::set<UndirectedEdge> line_keys;
  for (const auto& line : output->polylines) {
    if (line == nullptr) continue;
    for (int i = 0; i + 1 < line->num_vertices(); ++i) {
      line_keys.insert(MakeUndirectedEdge(line->vertex(i), line->vertex(i + 1)));
    }
  }

  std::vector<LoopData> loops;
  loops.reserve(lax_polygon.num_loops());
  std::map<UndirectedEdge, EdgeGroup> edge_groups;
  bool has_full_loop = false;
  for (int loop_index = 0; loop_index < lax_polygon.num_loops();
       ++loop_index) {
    const int vertex_count = lax_polygon.num_loop_vertices(loop_index);
    if (vertex_count == 0) {
      has_full_loop = true;
      loops.push_back({});
      continue;
    }
    LoopData loop;
    loop.vertices.reserve(vertex_count);
    loop.remove_edge.assign(vertex_count, false);
    for (int vertex = 0; vertex < vertex_count; ++vertex) {
      loop.vertices.push_back(lax_polygon.loop_vertex(loop_index, vertex));
    }
    const size_t stored_loop_index = loops.size();
    for (size_t edge_index = 0; edge_index < loop.vertices.size();
         ++edge_index) {
      const S2Point& a = loop.vertices[edge_index];
      const S2Point& b = loop.vertices[(edge_index + 1) % loop.vertices.size()];
      const PointKey a_key = KeyForPoint(a);
      const PointKey b_key = KeyForPoint(b);
      if (a_key == b_key) {
        loop.remove_edge[edge_index] = true;
        AddUniquePoint(a, &point_keys, output);
        continue;
      }
      if (b_key < a_key) {
        edge_groups[{b_key, a_key}].reverse.push_back(
            {stored_loop_index, edge_index});
      } else {
        edge_groups[{a_key, b_key}].forward.push_back(
            {stored_loop_index, edge_index});
      }
    }
    loops.push_back(std::move(loop));
  }

  for (const auto& entry : edge_groups) {
    const EdgeGroup& group = entry.second;
    const size_t paired_count = std::min(group.forward.size(),
                                         group.reverse.size());
    for (size_t i = 0; i < paired_count; ++i) {
      const EdgeReference& forward = group.forward[i];
      const EdgeReference& reverse = group.reverse[i];
      loops[forward.loop_index].remove_edge[forward.edge_index] = true;
      loops[reverse.loop_index].remove_edge[reverse.edge_index] = true;
      const LoopData& loop = loops[forward.loop_index];
      const S2Point& a = loop.vertices[forward.edge_index];
      const S2Point& b = loop.vertices[(forward.edge_index + 1) %
                                       loop.vertices.size()];
      if (!AddUniqueLine(a, b, &line_keys, output, error)) return false;
    }
  }

  std::vector<std::unique_ptr<S2Loop>> polygon_loops;
  for (const LoopData& loop : loops) {
    if (loop.vertices.empty()) continue;
    std::vector<size_t> kept_edges;
    for (size_t i = 0; i < loop.remove_edge.size(); ++i) {
      if (!loop.remove_edge[i]) kept_edges.push_back(i);
    }
    if (kept_edges.empty()) continue;
    std::vector<S2Point> vertices;
    vertices.reserve(kept_edges.size());
    for (size_t i = 0; i < kept_edges.size(); ++i) {
      const size_t edge_index = kept_edges[i];
      const size_t next_edge_index = kept_edges[(i + 1) % kept_edges.size()];
      const S2Point& edge_end =
          loop.vertices[(edge_index + 1) % loop.vertices.size()];
      const S2Point& next_start = loop.vertices[next_edge_index];
      if (edge_end != next_start) {
        return Fail(error,
                    "polygon degeneracy split a boundary into an open chain");
      }
      vertices.push_back(loop.vertices[edge_index]);
    }
    if (vertices.size() < 3) {
      return Fail(error, "polygon output retained a short non-degenerate loop");
    }
    auto polygon_loop = std::make_unique<S2Loop>(vertices, S2Debug::DISABLE);
    S2Error loop_error;
    if (polygon_loop->FindValidationError(&loop_error)) {
      return Fail(error, std::string("invalid polygon loop after contact split: ") +
                             std::string(loop_error.message()));
    }
    polygon_loops.push_back(std::move(polygon_loop));
  }

  output->polygon.set_s2debug_override(S2Debug::DISABLE);
  if (has_full_loop) {
    if (!polygon_loops.empty()) {
      return Fail(error, "full polygon result also contains area loops");
    }
    output->polygon = S2Polygon::MakeFull();
  } else if (!polygon_loops.empty()) {
    output->polygon.InitOriented(std::move(polygon_loops));
    S2Error polygon_error;
    if (output->polygon.FindValidationError(&polygon_error)) {
      return Fail(error, std::string("invalid polygon after contact split: ") +
                             std::string(polygon_error.message()));
    }
  }
  return true;
}

}  // namespace local_ee_s2

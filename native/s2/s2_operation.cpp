#include "s2_internal.h"

#include <memory>
#include <utility>
#include <vector>

#include "s2/s2boolean_operation.h"
#include "s2/s2builder.h"
#include "s2/s2builder_graph.h"
#include "s2/s2builderutil_s2point_vector_layer.h"
#include "s2/s2builderutil_lax_polygon_layer.h"
#include "s2/s2debug.h"
#include "s2/s2point_vector_shape.h"

namespace local_ee_s2 {
namespace {

bool Fail(std::string* error, const std::string& message) {
  *error = message;
  return false;
}

bool DecodeOp(int op, S2BooleanOperation::OpType* type, std::string* error) {
  using OpType = S2BooleanOperation::OpType;
  switch (op) {
    case 4: *type = OpType::INTERSECTION; return true;
    case 5: *type = OpType::UNION; return true;
    case 6: *type = OpType::DIFFERENCE; return true;
    case 7: *type = OpType::SYMMETRIC_DIFFERENCE; return true;
    default: return Fail(error, "overlay operation code is invalid");
  }
}

class LaxPolylineVectorLayer final : public S2Builder::Layer {
 public:
  LaxPolylineVectorLayer(std::vector<S2Point>* points,
                         std::vector<std::unique_ptr<S2Polyline>>* polylines)
      : points_(points), polylines_(polylines) {}

  GraphOptions graph_options() const override {
    using DegenerateEdges = GraphOptions::DegenerateEdges;
    using DuplicateEdges = GraphOptions::DuplicateEdges;
    using SiblingPairs = GraphOptions::SiblingPairs;
    return GraphOptions(EdgeType::DIRECTED, DegenerateEdges::KEEP,
                        DuplicateEdges::MERGE, SiblingPairs::KEEP);
  }

  void Build(const Graph& graph, S2Error* error) override {
    using PolylineType = Graph::PolylineType;
    const auto paths = graph.GetPolylines(PolylineType::WALK);
    for (const auto& path : paths) {
      if (path.empty()) continue;
      std::vector<S2Point> vertices;
      vertices.reserve(path.size() + 1);
      vertices.push_back(graph.vertex(graph.edge(path.front()).first));
      for (S2Builder::Graph::EdgeId edge_id : path) {
        vertices.push_back(graph.vertex(graph.edge(edge_id).second));
      }

      std::vector<S2Point> distinct_vertices;
      distinct_vertices.reserve(vertices.size());
      for (const S2Point& vertex : vertices) {
        if (distinct_vertices.empty() || distinct_vertices.back() != vertex) {
          distinct_vertices.push_back(vertex);
        }
      }
      if (distinct_vertices.size() < 2) {
        if (!distinct_vertices.empty()) points_->push_back(distinct_vertices[0]);
        continue;
      }

      auto polyline = std::make_unique<S2Polyline>(distinct_vertices,
                                                   S2Debug::DISABLE);
      S2Error line_error;
      if (polyline->FindValidationError(&line_error)) {
        *error = line_error;
        return;
      }
      polylines_->push_back(std::move(polyline));
    }
  }

 private:
  std::vector<S2Point>* points_;
  std::vector<std::unique_ptr<S2Polyline>>* polylines_;
};

std::vector<std::unique_ptr<S2Builder::Layer>> MakeOutputLayers(
    std::vector<S2Point>* points,
    std::vector<std::unique_ptr<S2Polyline>>* polylines,
    S2LaxPolygonShape* polygon) {
  using DuplicateEdges = S2Builder::GraphOptions::DuplicateEdges;
  s2builderutil::S2PointVectorLayer::Options point_options;
  point_options.set_duplicate_edges(DuplicateEdges::MERGE);

  std::vector<std::unique_ptr<S2Builder::Layer>> layers;
  layers.reserve(3);
  layers.push_back(std::make_unique<s2builderutil::S2PointVectorLayer>(
      points, point_options));
  layers.push_back(std::make_unique<LaxPolylineVectorLayer>(points, polylines));
  s2builderutil::LaxPolygonLayer::Options polygon_options;
  polygon_options.set_degenerate_boundaries(
      s2builderutil::LaxPolygonLayer::Options::DegenerateBoundaries::KEEP);
  layers.push_back(std::make_unique<s2builderutil::LaxPolygonLayer>(
      polygon, polygon_options));
  return layers;
}

}  // namespace

bool RunOverlay(int op, const S2ShapeIndex& left, const S2ShapeIndex& right,
                S2MemoryTracker* tracker, GeometryOutput* result,
                std::string* error) {
  if (result == nullptr || tracker == nullptr || error == nullptr) {
    return Fail(error, "overlay state is null");
  }
  S2BooleanOperation::OpType type;
  if (!DecodeOp(op, &type, error)) return false;

  std::vector<S2Point> points;
  std::vector<std::unique_ptr<S2Polyline>> polylines;
  S2LaxPolygonShape lax_polygon;
  S2BooleanOperation::Options options;
  options.set_polygon_model(S2BooleanOperation::PolygonModel::CLOSED);
  options.set_polyline_model(S2BooleanOperation::PolylineModel::CLOSED);
  options.set_memory_tracker(tracker);
  S2BooleanOperation operation(
      type, MakeOutputLayers(&points, &polylines, &lax_polygon), options);
  S2Error s2_error;
  if (!operation.Build(left, right, &s2_error)) {
    return Fail(error, std::string("S2 Boolean operation failed: ") +
                           std::string(s2_error.message()));
  }
  result->points = std::move(points);
  result->polylines = std::move(polylines);
  if (!ExtractLaxPolygon(lax_polygon, result, error)) return false;
  return true;
}

bool AddOutputToIndex(GeometryOutput* output, S2MemoryTracker* tracker,
                      MutableS2ShapeIndex* index, std::string* error) {
  if (output == nullptr || tracker == nullptr || index == nullptr ||
      error == nullptr) {
    return Fail(error, "index output state is null");
  }
  bool overflow = false;
  const size_t wire_size = EstimateWireSize(*output, &overflow);
  if (overflow || wire_size > kMaxOutputDoubles) {
    return Fail(error,
                "normalized geometry exceeds an output shape, position, "
                "part, or wire bound");
  }

  index->set_memory_tracker(tracker);
  if (!output->points.empty()) {
    index->Add(std::make_unique<S2PointVectorShape>(std::move(output->points)));
  }
  for (auto& polyline : output->polylines) {
    if (polyline == nullptr || polyline->num_vertices() < 2) continue;
    std::unique_ptr<const S2Polyline> owned_polyline = std::move(polyline);
    index->Add(std::make_unique<S2Polyline::OwningShape>(
        std::move(owned_polyline)));
  }
  if (!output->polygon.is_empty()) {
    auto polygon = std::make_unique<S2Polygon>(std::move(output->polygon));
    std::unique_ptr<const S2Polygon> owned_polygon = std::move(polygon);
    index->Add(std::make_unique<S2Polygon::OwningShape>(
        std::move(owned_polygon)));
  }
  return true;
}

}  // namespace local_ee_s2

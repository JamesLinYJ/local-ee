"""Local adapters for the pinned official Earth Engine Python task API."""

from __future__ import annotations

import re
from typing import Any

if __package__:
    from .ee_python_exports import local_options, prepare_local_image_export
    from .ee_python_map import install_image_map_id
else:
    from ee_python_exports import local_options, prepare_local_image_export
    from ee_python_map import install_image_map_id


_OPERATION = re.compile(r"(?:^|/)operations/([^/]+)$")
_TASK_TO_OPERATION = {
    "UNSUBMITTED": "PENDING",
    "READY": "PENDING",
    "RUNNING": "RUNNING",
    "COMPLETED": "SUCCEEDED",
    "FAILED": "FAILED",
    "CANCELLED": "CANCELLED",
    "CANCEL_REQUESTED": "CANCELLING",
}
_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}


def _raise(ee: Any, message: str) -> None:
    raise ee.ee_exception.EEException(message)


def _unwrap(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise ValueError("Local EE task API returned an invalid response")
    value = response.get("value")
    return value if isinstance(value, dict) else response


def _job_id(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) == 1:
        value = value[0]
    match = _OPERATION.fullmatch(value) if isinstance(value, str) else None
    if match:
        return match.group(1)
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        return value
    raise ValueError("Local EE task ID is invalid")


def _operation(job_id: str, status: dict[str, Any]) -> dict[str, Any]:
    state = status.get("state", "UNKNOWN")
    metadata: dict[str, Any] = {
        "state": _TASK_TO_OPERATION.get(state, "UNSPECIFIED"),
    }
    for source, target in (("description", "description"), ("task_type", "type")):
        if isinstance(status.get(source), str):
            metadata[target] = status[source]
    operation: dict[str, Any] = {
        "name": "operations/" + job_id,
        "metadata": metadata,
        "done": state in _TERMINAL,
    }
    error = status.get("error_message")
    if state == "FAILED" and isinstance(error, str):
        operation["error"] = {"message": error[:500]}
    return operation


def install_tasks(ee: Any, send: Any, encode: Any) -> None:
    """Route official task operations to the short-lived local EE API token."""
    data = ee.data
    if getattr(data, "_local_ee_tasks_installed", False):
        return
    submitted: dict[str, str] = {}

    def request(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            result = send(payload)
        except ee.ee_exception.EEException:
            raise
        except Exception as error:
            _raise(ee, str(error)[:500] or "Local EE task request failed")
        if not isinstance(result, dict):
            _raise(ee, "Local EE task API returned an invalid response")
        return result

    def read_status(job: str) -> dict[str, Any]:
        response = _unwrap(request({"action": "status", "job_id": job}))
        if "state" not in response:
            _raise(ee, "Local EE task status is missing its state")
        return response

    def start_job(job: str) -> None:
        request({"action": "start", "job_id": job})

    def export(action: str, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        try:
            local = local_options(ee, action, params, encode)
            key = _job_id(request_id) if request_id else None
        except (TypeError, ValueError) as error:
            _raise(ee, str(error))
        if key and key in submitted:
            job = submitted[key]
            state = read_status(job).get("state")
            if state == "UNSUBMITTED":
                start_job(job)
            return {"name": "operations/" + job}
        if key is None:
            _raise(ee, "Local EE export requires an SDK request ID")
        payload = {
            "action": action,
            "expression": encode(local["expression"]),
            "options": local["options"],
            "request_id": key,
        }
        result = request(payload)
        job = result.get("job_id")
        if not isinstance(job, str) or not job or len(job) > 128:
            _raise(ee, "Local EE export did not return a task ID")
        submitted[key] = job
        if read_status(job).get("state") == "UNSUBMITTED":
            start_job(job)
        return {"name": "operations/" + job}

    def export_image(request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        return export("export_image", request_id, params)

    def export_table(request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        return export("export_table", request_id, params)

    def get_operation(name: str) -> dict[str, Any]:
        try:
            job = _job_id(name)
        except ValueError as error:
            _raise(ee, str(error))
        return _operation(job, read_status(job))

    def cancel_operation(name: str) -> None:
        try:
            job = _job_id(name)
        except ValueError as error:
            _raise(ee, str(error))
        request({"action": "cancel", "job_id": job})

    def get_task_status(task_ids: Any) -> list[dict[str, Any]]:
        ids = [task_ids] if isinstance(task_ids, str) else task_ids
        if not isinstance(ids, (list, tuple)):
            _raise(ee, "Task IDs must be a string or list")
        return [
            ee._cloud_api_utils.convert_operation_to_task(
                get_operation("operations/" + _job_id(task_id))
            )
            for task_id in ids
        ]

    def list_operations(project: str | None = None) -> list[dict[str, Any]]:
        if project is not None:
            _raise(ee, "Local task listing does not accept cloud project names")
        response = _unwrap(request({"action": "list"}))
        operations = response.get("operations")
        if not isinstance(operations, list):
            _raise(ee, "Local task listing returned an invalid response")
        result = []
        for item in operations:
            if not isinstance(item, dict):
                _raise(ee, "Local task listing returned an invalid operation")
            if isinstance(item.get("metadata"), dict) and isinstance(item.get("name"), str):
                result.append(item)
            else:
                try:
                    job = _job_id(item.get("id"))
                except ValueError as error:
                    _raise(ee, str(error))
                result.append(_operation(job, item))
        return result

    def get_task_list() -> list[dict[str, Any]]:
        return [
            ee._cloud_api_utils.convert_operation_to_task(op)
            for op in list_operations()
        ]

    ee.batch._prepare_image_export_config = lambda image, config, destination: (
        prepare_local_image_export(ee, image, config, destination)
    )
    install_image_map_id(ee, send, encode)
    data.exportImage = export_image
    data.exportTable = export_table
    data.getOperation = get_operation
    data.getTaskStatus = get_task_status
    data.cancelOperation = cancel_operation
    data.cancelTask = lambda task_id: cancel_operation("operations/" + _job_id(task_id))
    data.listOperations = list_operations
    data.getTaskList = get_task_list
    data._local_ee_tasks_installed = True

"""One physical output boundary for publication and every result reader."""
from pathlib import Path
import stat
import uuid

def output_dir(root, job_id):
    text=str(job_id)
    if str(uuid.UUID(text)) != text:
        raise ValueError("Invalid job id")
    jobs=Path(root).resolve()/"jobs"
    job=jobs/text
    folder=job/"out"
    for path in (jobs,job,folder):
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise ValueError("Output directory must be a physical directory")
    if folder.resolve() != folder:
        raise ValueError("Output directory escaped its job")
    return folder

def artifact_path(root,job_id,name):
    if not isinstance(name,str) or not name or Path(name).name != name or name in {".",".."}:
        raise ValueError("Invalid artifact name")
    folder=output_dir(root,job_id);path=folder/name
    if not stat.S_ISREG(path.lstat().st_mode) or path.resolve().parent != folder:
        raise ValueError("Artifact must be a regular immediate child")
    return path

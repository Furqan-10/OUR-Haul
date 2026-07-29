"""The dependency manifest must install somewhere other than the machine that
wrote it.

The original requirements.txt was the Emergent platform *image* manifest, not
this application's dependency list. It named `emergentintegrations`, which is
not published on PyPI, and fetched litellm from customer-assets.emergentagent.com.
Both resolve inside that image and nowhere else -- and they fail at *build*
time on a deploy host, which is the worst moment to find out.
"""
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REQUIREMENTS = BACKEND / "requirements.txt"
DEV_REQUIREMENTS = BACKEND / "requirements-dev.txt"


def _requirement_lines(path=REQUIREMENTS):
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            yield line


def test_no_dependency_is_fetched_from_a_url():
    """A URL pin ties the build to one host staying up and serving that file."""
    offenders = [line for line in _requirement_lines()
                 if re.search(r"https?://|@\s*http|git\+", line)]
    assert not offenders, (
        "requirements.txt fetches a dependency from a URL:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse a PyPI release, or vendor the code into the repository."
    )


def test_no_dependency_is_unavailable_outside_the_platform():
    offenders = [line for line in _requirement_lines()
                 if "emergent" in line.lower()]
    assert not offenders, (
        "requirements.txt names a package that is not published on PyPI:\n  "
        + "\n  ".join(offenders)
        + "\n\nAI runs through providers/ai.py, which imports its SDK lazily "
          "inside chat(). With AI_PROVIDER=null it is never reached, so it must "
          "not be a build dependency."
    )


def test_dnspython_is_present_for_atlas_srv_uris():
    """MongoDB Atlas hands out mongodb+srv:// URIs, which need dnspython.

    Without it pymongo raises a configuration error that never mentions DNS, so
    the failure reads like a bad password and costs an afternoon.
    """
    assert any(line.lower().startswith("dnspython") for line in _requirement_lines()), (
        "dnspython is missing. MONGO_URL from Atlas begins mongodb+srv:// and "
        "cannot be resolved without it."
    )


def test_test_tooling_is_not_in_the_production_manifest():
    tooling = ("pytest", "black", "flake8", "mypy", "isort", "botocore", "boto3")
    offenders = [line for line in _requirement_lines()
                 if any(line.lower().startswith(name) for name in tooling)]
    assert not offenders, (
        "Test and lint tooling belongs in requirements-dev.txt, not the "
        "production image:\n  " + "\n  ".join(offenders)
    )


def test_a_dev_manifest_exists_and_includes_the_production_one():
    assert DEV_REQUIREMENTS.exists(), "requirements-dev.txt is missing."
    assert any(line.startswith("-r requirements.txt")
               for line in _requirement_lines(DEV_REQUIREMENTS)), (
        "requirements-dev.txt must start from requirements.txt, or the two "
        "drift and a dev environment stops matching production."
    )


def test_requirements_local_has_been_folded_in():
    assert not (BACKEND / "requirements-local.txt").exists(), (
        "requirements-local.txt existed only because requirements.txt could not "
        "be installed off-platform. Now that it can, keeping both guarantees drift."
    )


def test_every_module_imported_at_startup_is_declared():
    """Catch a package dropped from the manifest that server.py still imports.

    Import names and distribution names differ often enough (dotenv/python-dotenv,
    jwt/PyJWT) that this maps the ones this app uses rather than guessing.
    """
    declared = {re.split(r"[=<>\[]", line)[0].strip().lower()
                for line in _requirement_lines()}
    # import name -> distribution name
    expected = {
        "fastapi": "fastapi", "uvicorn": "uvicorn", "starlette": "starlette",
        "pydantic": "pydantic", "dotenv": "python-dotenv", "motor": "motor",
        "pymongo": "pymongo", "jwt": "pyjwt", "passlib": "passlib",
        "httpx": "httpx", "reportlab": "reportlab", "pypdf": "pypdf",
        "apscheduler": "apscheduler",
    }
    source = (BACKEND / "server.py").read_text(encoding="utf-8")
    missing = []
    for import_name, dist in expected.items():
        if re.search(rf"^\s*(import|from)\s+{re.escape(import_name)}\b",
                     source, re.MULTILINE) and dist.lower() not in declared:
            missing.append(f"  server.py imports `{import_name}` but `{dist}` is not declared")
    assert not missing, "requirements.txt is missing a package the app imports:\n" + "\n".join(missing)

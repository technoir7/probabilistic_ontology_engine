from railway_sdk import define_railway, github, project, service, volume
# This repository manages only its own resources in the environment. Other
# repositories export their own partial name.
# See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
PARTIAL = "epistemic-monitor-suite"
@define_railway
def main(ctx=None):
    # Holds every domain's SQLite database. `railway config migrate` leaves it
    # out because railway.toml never named it; declaring it keeps it mounted.
    data = volume("epistemic-monitor-suite-volume", region="us-west2", sizeMB=500)
    epistemicMonitorSuite = service(
        "epistemic-monitor-suite",
        source=github("technoir7/probabilistic_ontology_engine", **{ "branch": "main", "checkSuites": False }),
        build={ "buildEnvironment": "V3", "builder": "NIXPACKS" },
        start="uvicorn src.engine.api.app:app --host 0.0.0.0 --port $PORT",
        healthcheck="/health",
        healthcheckTimeout=300,
        replicas={ "us-west2": 1 },
        volumeMounts={ "/data": data },
    )
    return project("epistemic-monitor-suite", variables={"managed": False}, resources=[epistemicMonitorSuite, data])

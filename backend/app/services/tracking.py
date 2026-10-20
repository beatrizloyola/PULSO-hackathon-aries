import mlflow

from app import config


def init_tracking() -> str:
    """Aponta o MLflow para o tracking store do projeto e retorna o experiment_id.

    Com o store local (sqlite padrão) os artefatos vão para backend/mlruns,
    independente do diretório de onde o script foi chamado.
    """
    mlflow.set_tracking_uri(config.MLFLOW_TRACKING_URI)
    exp = mlflow.get_experiment_by_name(config.MLFLOW_EXPERIMENT)
    if exp is not None:
        mlflow.set_experiment(experiment_id=exp.experiment_id)
        return exp.experiment_id
    artifact_location = None
    if config.MLFLOW_TRACKING_URI.startswith("sqlite:"):
        artifact_location = config.MLFLOW_ARTIFACT_ROOT.as_uri()
    exp_id = mlflow.create_experiment(config.MLFLOW_EXPERIMENT,
                                      artifact_location=artifact_location)
    mlflow.set_experiment(experiment_id=exp_id)
    return exp_id

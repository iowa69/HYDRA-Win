"""HYDRA-Win: a portable Windows front end for the Hydra bacterial genome analyser."""

__version__ = "0.2.0"

#: The name users see: window title, executable, workbooks, README.
APP_NAME = "HYDRA-Win"
AUTHOR = "Giovanni Lorenzin"
ORGANISATION = "IOWA-BioTech"
REPO_URL = "https://github.com/iowa69/HYDRA-Win"

#: The upstream Hydra commit vendored under src/hydra_amr (see VENDORED.txt there).
UPSTREAM_URL = "https://github.com/iowa69/hydra"
UPSTREAM_COMMIT = "6d36c109491c16544e8919fe6962b4b62e97d3d7"

__all__ = ["__version__", "APP_NAME", "AUTHOR", "ORGANISATION", "REPO_URL", "UPSTREAM_URL",
           "UPSTREAM_COMMIT"]

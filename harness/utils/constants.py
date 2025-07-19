from loguru import logger
import subprocess
from pathlib import Path

# Constants - Installation Specifications

CODEPATHS = {
    "6mini_holidayskr": {
        "code_paths": ["holidayskr"],
        "test_paths": ["tests"],
    },
    "chrisK824_retry": {
        "code_paths": ["retry_reloaded"],
        "test_paths": ["tests"],
    },
    "DanielAvdar_pandas-pyarrow": {
        "code_paths": ["pandas_pyarrow", "docs"],
        "test_paths": ["tests"],
    },
    "databrickslabs_pylint-plugin": {
        "code_paths": ["src", "scripts"],
        "test_paths": ["tests"],
    },
    "pga2rn_simple-sqlite3-orm": {
        "code_paths": ["src"],
        "test_paths": ["tests"],
    },
    "pomponchik_emptylog": {
        "code_paths": ["docs", "emptylog"],
        "test_paths": ["tests"],
    },
    "simonw_files-to-prompt": {
        "code_paths": ["files_to_prompt"],
        "test_paths": ["tests"],
    },
    "sr-murthy_continuedfractions": {
        "code_paths": ["docs", "src"],
        "test_paths": ["tests"],
    },
    "ul-mds_gecko": {
        "code_paths": ["docs", "gecko"],
        "test_paths": ["tests"],
        "test_replace": [
            ["""assert _cldr.unescape_kb_char("\\\\u{22}") == '"'  # unicode entities should be decoded""", ""]
        ]
    },
    "yezz123_pgqb": {
        "code_paths": ["pgqb", "scripts"],
        "test_paths": ["tests"],
    },
    "thomasborgen_hypermedia":{
        "code_paths": ["hypermedia"],
        "test_paths": ["tests"],
    },
    "amaslyaev_noorm":{
        "code_paths": ["noorm"],
        "test_paths": ["tests"],
    },
    "Halvani_alphabetic":{
        "code_paths": ["alphabetic", "Demo.ipynb"],
        "test_paths": ["tests"],
    },
    "Peter-van-Tol_pydantic-shapely":{
        "code_paths": ["docs", "src"],
        "test_paths": ["tests", "test_api.old", "test_api.py", "test.py"],
    },
    "andrew000_FTL-Extract":{
        "code_paths": ["src"],
        "test_paths": ["tests"],
    },
    "dnlzrgz_memotica":{
        "code_paths": ["src"],
        "test_paths": ["tests"],
    },
    "ItsNotSoftware_lions":{
        "code_paths": ["lionsc", "examples"],
        "test_paths": ["tests"],
    },
    "BrianWeiHaoMa_csvuniondiff":{
        "code_paths": ["csvuniondiff"],
        "test_paths": ["tests"],
    },
    "makyol_landusemix":{
        "code_paths": ["docs","landusemix"],
        "test_paths": ["tests"],
    },
    "ParisNeo_pipmaster":{
        "code_paths": ["pipmaster", "docs", "examples"],
        "test_paths": ["tests"],
    },
    
    "Minibrams_fastapi-decorators":{
        "code_paths": ["docs", "docs-overrides", "fastapi_decorators"],
        "test_paths": ["tests"],
    },
    "uladkaminski_pyparseit":{
        "code_paths": ["examples", "pyparseit", "scripts"],
        "test_paths": ["tests"],
    },
    "adamtheturtle_doccmd":{
        "code_paths": ["bin", "docs", "src"],
        "test_paths": ["tests"],
    },
    "dimitarOnGithub_temporals":{
        "code_paths": ["temporals"],
        "test_paths": ["tests"],
    },
    "nineteendo_jsonyx":{
        "code_paths": ["bench", "docs", "src"],
        "test_paths": ["tests"],
    },
    "altcha-org_altcha-lib-py":{
        "code_paths": ["altcha"],
        "test_paths": ["tests"],
    },
    "danbailo_bpmn-parser":{
        "code_paths": ["bpmn_parser", "docs"],
        "test_paths": ["tests"],
    },
    "e-kotov_rewe-ebon-parser":{
        "code_paths": ["docs", "src"],
        "test_paths": ["tests"],
    },
    "erivlis_mappingtools":{
        "code_paths": ["src"],
        "test_paths": ["tests"],
    },
    "yowoda_autopep695":{
        "code_paths": ["autopep695", "changes", "scripts", "noxfile.py"],
        "test_paths": ["tests"],
    },
    
    "openscilab_memor":{
        "code_paths": ["memor", "otherfiles"],
        "test_paths": ["tests"],
    },
    "denisalevi_bib4llm":{
        "code_paths": ["bib4llm"],
        "test_paths": ["tests"],
    },
    "Maxim-Mushizky_cstructpy":{
        "code_paths": ["src"],
        "test_paths": ["unit_tests"],
    },
    "aio-libs_propcache":{
        "code_paths": ["docs", "packaging", "src"],
        "test_paths": ["tests"],
    },
    "vigsun19_smartprofiler":{
        "code_paths": ["examples", "smartprofiler"],
        "test_paths": ["tests"],
    },
    "amaziahub_mimicker":{
        "code_paths": ["mimicker"],
        "test_paths": ["tests"],
    },
    "Zozi96_hash-forge":{
        "code_paths": ["src"],
        "test_paths": ["tests"],
    },
    "RyderCRD_sagkit":{
        "code_paths": ["src"],
        "test_paths": ["tests"],
    },
    "silvio-machado_br-eval":{
        "code_paths": ["br_eval"],
        "test_paths": ["tests"],
    },
    "sklearn-compat_sklearn-compat":{
        "code_paths": ["docs", "src"],
        "test_paths": ["tests"],
    },
    
    "austinyu_ujson5":{
        "code_paths": ["docs", "release", "src"],
        "test_paths": ["tests"],
    },
    "tecnosam_pydongo":{
        "code_paths": ["docs", "examples", "pydongo"],
        "test_paths": ["tests"],
    },
    "jhd3197_Tukuy":{
        "code_paths": ["tukuy", "examples.py"],
        "test_paths": ["tests"],
    },
    "Undertone0809_conftier":{
        "code_paths": ["conftier", "docs", "examples"],
        "test_paths": ["tests"],
    },
    "encypherai_encypher-ai":{
        "code_paths": ["docs", "encypher"],
        "test_paths": ["tests"],
    },
    "plurch_ir_evaluation":{
        "code_paths": ["src"],
        "test_paths": ["tests"],
    },
    "Alburrito_mongo-migrator":{
        "code_paths": ["src"],
        "test_paths": ["tests"],
    },
    "microprediction_bonding":{
        "code_paths": ["bonding", "docs", "examples", "colab"],
        "test_paths": ["tests"],
    },
    "c0dearm_yaru":{
        "code_paths": ["src"],
        "test_paths": ["tests"],
    },
    "ethanlchristensen_streamlit-rich-message-history":{
        "code_paths": ["docs", "streamlit_rich_message_history"],
        "test_paths": ["tests"],
    },
}

def check_env_cmd(cmd):
    return "pip install" in cmd or \
        cmd.strip().startswith("export ") or \
        cmd.strip().startswith("cp ") or \
        cmd.strip().startswith("mkdir ")

def apply_patch(patch_file: Path, local_dir: Path) -> None:
    """Apply a patch to a local directory."""

    assert local_dir.is_dir()
    assert patch_file.exists()
    # The resolve() is important, because we're gonna run the cmd
    # somewhere else
    # Add a newline to the end of the patch file if it doesn't have one.
    # This is to prevent `git apply` from failing with "corrupt patch"
    try:
        with open(patch_file, 'rb+') as f:
            # Check if the file is not empty
            if f.seek(0, 2) > 0:
                # Go to the last byte of the file
                f.seek(-1, 2)
                # Check if it's a newline
                if f.read() != b'\n':
                    # If not, add a newline at the end
                    f.write(b'\n')
    except Exception as e:
        logger.warning(f"Could not fix patch file {patch_file}: {e}")
    cmd = ["git", "apply", 
           "--exclude", "*__pycache__*", 
           "--exclude", "*.pdf", 
           "--exclude", "*.db",
           "--exclude", "*.editorconfig", 
           "--exclude", "*.gitattributes", 
           "--exclude", "*.json5", 
           "--exclude", "new_tests*test_parsing*.json", 
           "--exclude", "*.shx", 
           "--exclude", "*.shp", 
           "--exclude", "*.dbf", 
           "--exclude", "*.tif", 
           "--exclude", "requirements.txt",
           "--exclude", "*.xlsx",
           "--exclude", "*.qix",
           str(patch_file.resolve())]
    try:
        subprocess.run(cmd, cwd=local_dir, check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to apply patch {patch_file} to {local_dir}: {e}")
        return False
    logger.info(f"Applied patch {patch_file} to {local_dir}")
    return True

SPECS_DEMO = {
    "python": "3.10",
    "pre_install": [
        "apt-get update && apt-get install -y locales",
        "echo 'en_US UTF-8' > /etc/locale.gen",
        "locale-gen en_US.UTF-8",
    ],
    "install": "python -m pip install -v --no-use-pep517 --no-build-isolation -e .",
    "pip_packages": [
        "cython",
        "numpy==1.19.2",
        "setuptools",
        "scipy==1.5.2",
    ],
    "test_cmd": "pytest --no-header -rA --tb=no -p no:cacheprovider",
}

SPECS_PYDANCLICK = {
    "pip_packages": [
        "pydantic==2.11.4",
        "pydantic_settings==2.9.0",
        "griffe==1.7.0",
    ],
    "ignore_tests": [
        "tests/test_examples.py::test_complex_types_example_help",
    ],
}

SPECS_BACKGROUNDER = {
    "pip_packages": [
        "esmerald==3.7.7",
        "httpx==0.28.1",
    ],
}

SPECS_DDDESIGN = {
    "pip_packages": [
        "parameterized==0.9.0",
    ],
}

SPECS_PYMINIRACER = {
    "pip_packages": [
        "mini_racer==0.12.4",
    ],
}

SPECS_REPORTMODIFIER = {
    "pip_packages": [
        "regex==2024.11.6",
    ],
}

SPECS_PANDAS_PYARROW = {
    "pip_packages": [
        "db_dtypes==1.4.2",
        "sybil==9.1.0",
        "hypothesis==6.131.15",
        "pytest-parametrization==2022.2.1",
    ],
}

SPECS_DUPLICATE_URL_DISCARDER = {
    "pip_packages": [
        "pytest-twisted==1.14.3",
    ],
}

SPECS_CONTINUEDFRACTIONS = {
    "pip_packages": [
        "pytest-xdist==3.6.1",
        "sympy==1.14.0",
    ],
}

SPECS_CSVUNIONDIFF = {
    "pre_install": [
        "pip install -i https://pypi.tuna.tsinghua.edu.cn/simple setuptools==79.0.1 wheel==0.45.1 pandas==2.2.3 ",
    ],
    "install": "git config --global --add safe.directory '*';\npip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple --default-timeout=600 --no-build-isolation",
}

SPECS_HYPERMEDIA = {
    "test_cmd": """PYTHONPATH=${PYTHONPATH:+$PYTHONPATH:}$(pwd) pytest --timeout=600 -rA --cov --cov-context=test -vv --cov-config=".coveragerc_tmp" --cov-report=json:coverage_report.json --json-report --json-report-file=pytest_report.json""",
}

SPECS_NOORM = {
    "pre_install": [
        r"""sed -i -E 's/^\s*documentation\s*=\s*""\s*$/#&/' pyproject.toml""",
    ],
    "pip_packages": [
        "-r requirements-dev.txt"
    ]
}

SPECS_LIONS = {
    "pre_install": [
        "mkdir -p tests/test_files/single_lmsg_file2/output",
    ],
}

SPECS_PYDANTIC_SHAPELY = {
    "pre_install": [
        "git config --global --add safe.directory '*'",
    ],
}

SPECS_PYDANTIC_FILE_SECRETS = {
    "pip_packages": [
        "doctestcase==0.2.2",
        "dirlay==0.4.0"
    ],
}

SPECS_FASTAPI_DECORATORS = {
    "pip_packages": [
        "httpx==0.28.1",
    ],
}

SPECS_IDEADENSITY = {
    "post_install": [
        "bash -c 'export HTTPS_PROXY=http://172.17.0.1:10809 && python -m spacy download en_core_web_sm'",
    ],
}

SPECS_MIMICKER = {
    "pip_packages": [
        "PyHamcrest==2.1.0",
        "requests==2.32.3",
    ],
    "pre_install": [
        "export https_proxy=",
        "export http_proxy=",
    ],
    "test_cmd": """all_proxy= http_proxy= https_proxy= pytest --timeout=600 -rA --cov --cov-context=test -vv --cov-config=".coveragerc_tmp" --cov-report=json:coverage_report.json --json-report --json-report-file=pytest_report.json"""
}

SPECS_HASH_FORGE = {
    "pip_packages": [
        "pycryptodome==3.22.0",
        "bcrypt==4.3.0",
        "blake3==1.0.4",
        "argon2-cffi==23.1.0",
    ],
}

SPECS_PROPCACHE = {
    "pip_packages": [
        "covdefaults==2.3.0",
        "Cython==3.1.0",
        "pytest-xdist==3.6.1",
    ],
}

SPECS_EMPTYLOG = {
    "pip_packages": [
        "full_match==0.0.2",
        "loguru==0.7.3"
    ],
}

SPECS_HOLIDAYS = {
    "pre_install": [
        r"""sed -i 's/{{VERSION_PLACEHOLDER}}/0.1.0/g' setup.py""",
    ],
    "test_cmd": """all_proxy=http://172.17.0.1:10809 pytest --timeout=600 -rA --cov --cov-context=test -vv --cov-config=".coveragerc_tmp" --cov-report=json:coverage_report.json --json-report --json-report-file=pytest_report.json""",
    
}

SPECS_FILES_TO_PROMPT = {
    "pre_install": [
        r"""sed -i 's/CliRunner(mix_stderr=False)/CliRunner()/g' tests/test_files_to_prompt.py""",
    ],
    "test_cmd": f"""PYTHONPATH=.:$PYTHONPATH pytest --timeout=600 -rA --cov --cov-context=test -vv --cov-config=".coveragerc_tmp" --cov-report=json:coverage_report.json --json-report --json-report-file=pytest_report.json"""
}

SPECS_MONGO_MIGRATOR = {
    "pip_packages": [
        "mongomock==4.3.0",
    ],
}

SPECS_CONFTIER = {
    "test_cmd": """pytest tests/ --timeout=600 -rA --cov --cov-context=test -vv --cov-config=".coveragerc_tmp" --cov-report=json:coverage_report.json --json-report --json-report-file=pytest_report.json""",
}

SPECS_FASTAPI_MCP = {
    "test_cmd": """pytest --ignore tests/test_sse_real_transport.py --timeout=600 -rA --cov --cov-context=test -vv --cov-config=".coveragerc_tmp" --cov-report=json:coverage_report.json --json-report --json-report-file=pytest_report.json""",
}

SPECS_BPMN_PARSER = {
    "pip_packages": [
        "lxml==5.4.0",
    ],
}

SPECS_AUTOPEP695 = {
    "pip_packages": [
        "libcst==1.8.2",
    ],
}

SPECS_PYDANTIC_FILE_SECRETS = {
    "pip_packages": [
        "fastapi==0.115.14",
    ],
}

SPECS_DOCCMD = {
    "pip_packages": [
        "ansi==0.3.7",
        "pytest_regressions==2.8.1"
    ],
}

SPECS_UJSON5 = {
    "pre_install": [
        r"""sed -i 's/_version.py//g' .gitignore""",
    ],
}

REPO_SPECS = {
    "felix-martel_pydanclick": SPECS_PYDANCLICK,
    "dymmond_backgrounder": SPECS_BACKGROUNDER,
    "davyddd_dddesign": SPECS_DDDESIGN,
    "bpcreech_PyMiniRacer": SPECS_PYMINIRACER,
    "MarketSquare_robotframework-reportmodifier": SPECS_REPORTMODIFIER,
    "DanielAvdar_pandas-pyarrow": SPECS_PANDAS_PYARROW,
    "zytedata_duplicate-url-discarder": SPECS_DUPLICATE_URL_DISCARDER,
    "sr-murthy_continuedfractions": SPECS_CONTINUEDFRACTIONS,
    "BrianWeiHaoMa_csvuniondiff": SPECS_CSVUNIONDIFF,
    "zytedata_csvuniondiff": SPECS_CSVUNIONDIFF,
    "thomasborgen_hypermedia": SPECS_HYPERMEDIA,
    "amaslyaev_noorm": SPECS_NOORM,
    "ItsNotSoftware_lions": SPECS_LIONS,
    "Peter-van-Tol_pydantic-shapely": SPECS_PYDANTIC_SHAPELY,
    "makukha_pydantic-file-secrets": SPECS_PYDANTIC_FILE_SECRETS,
    "Minibrams_fastapi-decorators": SPECS_FASTAPI_DECORATORS,
    "jrrobison1_ideadensity": SPECS_IDEADENSITY,
    "amaziahub_mimicker": SPECS_MIMICKER,
    "Zozi96_hash-forge": SPECS_HASH_FORGE,
    "aio-libs_propcache": SPECS_PROPCACHE,
    "pomponchik_emptylog": SPECS_EMPTYLOG,
    "6mini_holidayskr": SPECS_HOLIDAYS,
    "simonw_files-to-prompt": SPECS_FILES_TO_PROMPT,
    "Alburrito_mongo-migrator": SPECS_MONGO_MIGRATOR,
    "Undertone0809_conftier": SPECS_CONFTIER,
    "tadata-org_fastapi_mcp": SPECS_FASTAPI_MCP,
    "danbailo_bpmn-parser": SPECS_BPMN_PARSER,
    "yowoda_autopep695": SPECS_AUTOPEP695,
    "Minibrams_fastapi-decorators": SPECS_FASTAPI_DECORATORS,
    "adamtheturtle_doccmd": SPECS_DOCCMD,
    "austinyu_ujson5": SPECS_UJSON5,
}

def get_pip_packages(repo_name):
    if repo_name in REPO_SPECS and "pip_packages" in REPO_SPECS[repo_name]:
        return REPO_SPECS[repo_name]["pip_packages"]
    else:
        logger.info(f"No pip_packages found for repo {repo_name}, using default installation.")
        return None

def get_ignore_tests(repo_name):
    if repo_name in REPO_SPECS and "ignore_tests" in REPO_SPECS[repo_name]:
        return REPO_SPECS[repo_name]["ignore_tests"]
    else:
        logger.info(f"No ignore_tests found for repo {repo_name}, using all tests.")
        return None

def get_pre_install(repo_name):
    if repo_name in REPO_SPECS and "pre_install" in REPO_SPECS[repo_name]:
        return REPO_SPECS[repo_name]["pre_install"]
    else:
        return None

def get_post_install(repo_name):
    if repo_name in REPO_SPECS and "post_install" in REPO_SPECS[repo_name]:
        return REPO_SPECS[repo_name]["post_install"]
    else:
        return None

def get_install(repo_name):
    if repo_name in REPO_SPECS and "install" in REPO_SPECS[repo_name]:
        return REPO_SPECS[repo_name]["install"]
    else:
        return None

def get_test_cmd(repo_name):
    if repo_name in REPO_SPECS and "test_cmd" in REPO_SPECS[repo_name]:
        return REPO_SPECS[repo_name]["test_cmd"]
    else:
        return None
#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="aidev"
PYTHON=(conda run -n "${ENV_NAME}" python)

if ! conda env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  echo "请先创建环境：conda create -n ${ENV_NAME} python=3.11 -y" >&2
  exit 1
fi

conda install -n "${ENV_NAME}" numpy=1.24.3 pandas=2.1.1 scikit-learn cryptography -y

"${PYTHON[@]}" -m pip install python-dotenv faiss-cpu==1.7.4 metagpt==0.8.1 --no-deps
"${PYTHON[@]}" -m pip install --no-deps \
  pydantic==2.6.4 pydantic-core==2.16.3 annotated-types \
  tenacity==8.2.3 typing-extensions==4.9.0 typing-inspect==0.8.0 mypy-extensions \
  loguru==0.6.0 PyYAML==6.0.1 rich==13.6.0 markdown-it-py mdurl pygments \
  tqdm==4.66.2 typer==0.9.0 click networkx==3.2.1 \
  openai==1.6.1 anthropic==0.18.1 aiofiles==23.2.1 aiohttp==3.8.6 \
  attrs charset-normalizer multidict async-timeout yarl frozenlist aiosignal \
  fire==0.4.0 termcolor gitpython==3.1.40 gitdb smmap gitignore-parser==0.1.9 \
  anyio distro httpx==0.27.2 httpcore==1.0.9 h11 sniffio idna certifi propcache tokenizers
"${PYTHON[@]}" -m pip install --no-deps \
  python-docx tiktoken chardet beautifulsoup4 playwright imap-tools anytree openpyxl \
  rank-bm25 socksio websocket-client websockets wrapt jieba ta nbclient nbformat \
  google-generativeai dashscope qianfan zhipuai soupsieve \
  google-ai-generativelanguage google-api-core google-auth protobuf grpcio proto-plus \
  googleapis-common-protos pyasn1-modules pyasn1 httplib2 google-auth-httplib2 \
  uritemplate pyparsing semantic-kernel==0.4.3.dev0 \
  aiolimiter bce-python-sdk diskcache multiprocess prompt-toolkit dill wcwidth future crc32c \
  requests urllib3 Pillow regex lxml pyee greenlet cachetools pyjwt pycryptodome pytest pytest-cov

"${PYTHON[@]}" -c "from metagpt.roles import Architect, Engineer, ProductManager, ProjectManager, QaEngineer; print('metagpt roles import ok')"

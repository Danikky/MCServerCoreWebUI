echo Searching directory...
cd */MCServerCoreWebUI
echo done.

echo Creating env...
python3 -m venv .venv
echo done.

echo Activating env...
source .venv/bin/activate.fish
echo done.

echo Installing libraries...
pip install -r requirements.txt
echo done.

echo Start main...
python3 main.py
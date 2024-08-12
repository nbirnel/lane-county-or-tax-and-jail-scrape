venv:
	python3 -m venv venv

requirements: venv
	. venv/bin/activate; pip install -r requirements.txt

browsers: venv
	. venv/bin/activate; playwright install

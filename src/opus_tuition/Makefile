# Define the command
start:
	@echo "--- Activate virtual environment ---"
	source ./myvenv/bin/activate
	@echo "--- Starting server ---"
	python3 manage.py runserver

.PHONY: start


process:
	@echo "--- Starting automated file processing ---"
	python3 run_automated_data_processing.py
	@echo "--- Pipeline finished ---"

.PHONY: process



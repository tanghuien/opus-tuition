# Define the command
start:
	@echo "--- Starting server ---"
	python3 manage.py runserver

.PHONY: start


process:
	@echo "--- Starting automated data processing ---"
	python3 run_automated_data_processing.py
	@echo "--- Pipeline finished ---"

.PHONY: process



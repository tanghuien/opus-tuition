# Define the command
start:
	@echo "--- Migrating database ---"
	python3 manage.py migrate
	@echo "--- Starting server ---"
	python3 manage.py runserver

.PHONY: start


process:
	@echo "--- Starting automated file processing ---"
	python3 run_automated_data_processing.py
	@echo "--- Pipeline finished ---"

.PHONY: process
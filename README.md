Ensure [pip3](https://pypi.org/project/pip/) and [python3](https://www.python.org) is installed.
<br>
1. Open the terminal
2. Download the project folder from [github](https://github.com/tanghuien/opus-tuition) then unzip the downloaded folder
3. Drag the unzipped folder to the terminal 
4. Navigate to source code: "<b>cd src/opus_tuition</b>"
5. Install virtual environment: "<b>python3 -m venv myvenv</b>"
6. Activate virtual environment: "<b>source ./myvenv/bin/activate</b>"
7. Install the packages: "<b>pip install -r requirements.txt</b>"
8. Aautomate the pipeline: "<b>make process</b>"
9. Run test scripts: "<b>python3 manage.py test</b>"

<b>* Bolded characters are to be entered in the terminal</b>

Repository structure 
```text
opus-tuition/
├── docs/
│   ├── architecture.md             ← Architecture Document
│   └── api-reference.md            ← API reference
├── src/
│   ├── data_cleaning/              ← Exploratory Data Analysis and playground
│   │   └── data/                   ← Outputs
│   └── opus_tuition/               ← Source code
│       └── uploads/                 
│           ├── uploaded_files/     ← Store raw files saved to the database
│           ├── data/               ← Store data for pipeline automation
│           │   ├── processed/      ← Store raw files still processing for pipeline automation
│           │   ├── quarantine/     ← Raw files tha
│           │   ├── raw/            ← Store raw file to process
│           │   └── report/         ← Store processing reports after pipeline automation
│           └── test.py             ← Test suite
├── README.md                       ← Setup instructions, architecture overview, demo video
├── .gitignore                      ← Ignore and stop tracking files 
└── .env.example                    ← Environment variable template         
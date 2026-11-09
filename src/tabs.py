"""The six Procore data tabs: sheet name, Excel table name and exact column order."""
from collections import OrderedDict

TABS = OrderedDict([
    ("daily_log", {
        "sheet": "Daily Log - Procore Data", "table": "Table19",
        "columns": ["Project Number", "Project Name", "Date", "Completed?"],
        "date_columns": ["Date"],
    }),
    ("safety_survey", {
        "sheet": "Safety Survey - Procore Data", "table": "Table6",
        "columns": ["Project Number", "Inspection Template Name", "Project Name", "Inspection #",
                    "Assignee(s)", "No Response", "Due Date", "Status", "Date Closed", "Closed By",
                    "Project Region", "# Of Observations", "At Risk Items"],
        "date_columns": ["Due Date", "Date Closed"],
        "int_columns": ["No Response", "# Of Observations", "At Risk Items"],
    }),
    ("observations", {
        "sheet": "Observations - Procore Data", "table": "Table18",
        "columns": ["Project Number", "Project Name", "#", "Category", "Status", "Date Created",
                    "Column3", "Column2", "Column1"],
        "date_columns": ["Date Created"],
        # Column1 is a calculated column; the writer puts the formula back on every row
        "formulas": {"Column1": 'IF(Table18[[#This Row],[Status]]="Closed","Closed","Open")'},
    }),
    ("utv", {
        "sheet": "UTV - Procore Data", "table": "Table3",
        "columns": ["Inspection Template Name", "Project Number", "Project Name", "Status",
                    "Date Created", "Date Closed", "Created By", "Closed By"],
        "date_columns": ["Date Created", "Date Closed"],
    }),
    ("incident_forms", {
        "sheet": "Incident Forms - Procore Data", "table": "Table4",
        "columns": ["Template Name", "Project Number", "Project Name", "Date", "Title", "Description"],
        "date_columns": ["Date"],
    }),
    ("incidents", {
        "sheet": "Incidents Tab - Procore Data", "table": "Table5",
        "columns": ["Project Number", "Project Name", "#", "Status", "Incident Date", "Title",
                    "Recordable", "Description"],
        "date_columns": ["Incident Date"],
    }),
])

"""Mock data for demos and tests: ~15 employer job profiles and ~85 applicant profiles.

Everything here is invented for an Espoo recruitment event demo. The profiles are anonymous by
design (no names, ages, genders, nationalities or contact details), just like real ones.
Skills are written as exact ESCO labels and resolved to their URIs from esco/skills_meta.json;
the loader stops with search suggestions if a label does not exist. The profiles go through the
real Pydantic models (employer.JobProfile, applicant.ApplicantProfile), so every point rule holds.

The applicants are designed to exercise matching. Each one has a `note` (not stored) that says
what it is for: a strong fit for a job (same ESCO skills), the same skills with other priorities,
a near fit (different but similar ESCO skills), a partial fit, a career changer, an international
profile, or no fit at all.

Validation questions come from ApplicantFlow.questions_for() (the shared cache in
data/validation_questions.json; uncached skills cost one Gemini call per batch and need
GEMINI_API_KEY). Validation answers are hand-written below; some are empty (skipped).

All ids start with `mock-`, so seeding replaces the mock entries and never touches real ones.

Usage:
    .venv/bin/python seed_mock.py           # delete all mock-* entries, then insert the mock data
    .venv/bin/python seed_mock.py --clear   # only delete all mock-* jobs and applicants
    .venv/bin/python seed_mock.py --check   # only resolve the labels and validate the profiles
"""

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from applicant import make_applicant_profile
from employer import Flag, JobProfile, RequiredSkill, Task

ROOT = Path(__file__).resolve().parent
META_PATH = ROOT / "esco" / "skills_meta.json"
MOCK_PREFIX = "mock-"

# Language skills are usually added by hand (the AI rarely suggests them).
LANGUAGES = {"Finnish", "interact verbally in Finnish", "understand spoken Finnish", "write Finnish",
             "understand written Finnish", "English", "Swedish", "Russian", "Ukrainian", "Arabic",
             "Estonian", "Persian", "Vietnamese", "Chinese", "Spanish", "French", "German"}


# ---------- Jobs ----------
# Each task lists its ESCO skills with the employer's points. A skill's priority and tasks come
# from the task it belongs to. Points over all tasks sum to exactly 10.

JOBS = [
    {
        "id": "mock-job-01",
        "title": "Frontend Developer (React)",
        "summary": "Build and maintain the customer-facing web app of an Espoo software company in React and TypeScript. "
                   "Work with a designer and two backend developers, and fix bugs reported by customers.",
        "tasks": [
            {"task": "Build new views for the customer web app in React and TypeScript", "priority": "must_have",
             "skills": {"JavaScript Framework": 3, "JavaScript": 2, "TypeScript": 1}},
            {"task": "Find and fix bugs reported by customers in the web app", "priority": "must_have",
             "skills": {"debug software": 2}},
            {"task": "Turn the designer's wireframes into responsive pages", "priority": "learnable",
             "skills": {"implement front-end website design": 2}},
        ],
        "flags": [],
    },
    {
        "id": "mock-job-02",
        "title": "Backend Developer (Python)",
        "summary": "Develop the REST API and database of a booking service used by sports halls in Espoo. "
                   "Investigate production errors and add automated tests to the code you touch.",
        "tasks": [
            {"task": "Develop REST API endpoints for the booking service in Python", "priority": "must_have",
             "skills": {"Python (computer programming)": 3, "use an application-specific interface": 1}},
            {"task": "Design tables and write queries for the PostgreSQL database", "priority": "must_have",
             "skills": {"SQL": 2, "design database scheme": 1}},
            {"task": "Investigate and fix errors reported from production", "priority": "must_have",
             "skills": {"debug software": 2}},
            {"task": "Write automated tests for new and changed code", "priority": "learnable",
             "skills": {"develop automated software tests": 1}},
        ],
        "flags": [
            {"requirement": "Master's degree in computer science required",
             "concern": "The tasks are API and database work that people with a bachelor's degree, a bootcamp or "
                        "self-taught experience also do. Ask for demonstrated Python and SQL skills instead."},
        ],
    },
    {
        "id": "mock-job-03",
        "title": "Data Engineer",
        "summary": "Build and run the pipelines that load data from a retailer's source systems into its data warehouse. "
                   "Clean and validate incoming data so that the analysts can trust the reports.",
        "tasks": [
            {"task": "Build ETL pipelines that load sales data from source systems into the data warehouse",
             "priority": "must_have",
             "skills": {"data extraction, transformation and loading tools": 3, "data warehouse": 2}},
            {"task": "Write SQL transformations for reporting tables", "priority": "must_have",
             "skills": {"SQL": 2}},
            {"task": "Clean and validate incoming data before it is loaded", "priority": "learnable",
             "skills": {"perform data cleansing": 1}},
            {"task": "Run and schedule the pipelines on the cloud platform with Python scripts", "priority": "learnable",
             "skills": {"cloud technologies": 1, "Python (computer programming)": 1}},
        ],
        "flags": [],
    },
    {
        "id": "mock-job-04",
        "title": "Software Tester (QA)",
        "summary": "Test a mobile banking app before each release and report the bugs you find clearly to developers. "
                   "Plan test cases for new features and, over time, automate the regression tests.",
        "tasks": [
            {"task": "Run manual and exploratory tests on each release candidate", "priority": "must_have",
             "skills": {"execute software tests": 3}},
            {"task": "Write clear bug reports with steps to reproduce", "priority": "must_have",
             "skills": {"report test findings": 2}},
            {"task": "Plan test cases for new features together with the product owner", "priority": "learnable",
             "skills": {"plan software testing": 2, "develop ICT test suite": 1}},
            {"task": "Automate the most important regression tests", "priority": "nice_to_have",
             "skills": {"develop automated software tests": 2}},
        ],
        "flags": [],
    },
    {
        "id": "mock-job-05",
        "title": "IT Support Specialist",
        "summary": "Help the staff of Espoo schools with their computers, printers and accounts, by phone and on site. "
                   "Install software and keep track of support requests in the help desk system.",
        "tasks": [
            {"task": "Help teachers and office staff with computer problems by phone and on site", "priority": "must_have",
             "skills": {"provide ICT support": 3, "support ICT system users": 2}},
            {"task": "Troubleshoot broken laptops, printers and network connections", "priority": "must_have",
             "skills": {"troubleshoot": 2}},
            {"task": "Install software and operating systems on new laptops", "priority": "learnable",
             "skills": {"install software": 1, "install operating system": 1}},
            {"task": "Log and follow up support requests in the help desk system", "priority": "learnable",
             "skills": {"ICT help platforms": 1}},
        ],
        "flags": [
            {"requirement": "Fluent Finnish and Swedish required",
             "concern": "Most support requests come in Finnish, but Swedish is only needed in two schools. "
                        "Consider working Finnish as the requirement and Swedish as a bonus."},
        ],
    },
    {
        "id": "mock-job-06",
        "title": "Customer Service Agent",
        "summary": "Answer the calls and chats of an energy company's household customers in Finnish. "
                   "Solve billing questions and complaints, and record every case in the CRM.",
        "tasks": [
            {"task": "Answer customer phone calls and chat messages about contracts and bills", "priority": "must_have",
             "skills": {"answer incoming calls": 2, "respond to customers' inquiries": 3}},
            {"task": "Handle complaints about bills and service breaks", "priority": "must_have",
             "skills": {"handle customer complaints": 2}},
            {"task": "Record every customer case in the CRM system", "priority": "learnable",
             "skills": {"customer relationship management": 1}},
            {"task": "Serve customers in Finnish on the phone", "priority": "must_have",
             "skills": {"interact verbally in Finnish": 2}},
        ],
        "flags": [
            {"requirement": "Native Finnish required",
             "concern": "The calls need good spoken Finnish, not native Finnish. Ask for the level the work "
                        "actually needs, so fluent non-native speakers are not excluded."},
        ],
    },
    {
        "id": "mock-job-07",
        "title": "Bookkeeper",
        "summary": "Keep the books of small business clients at an accounting firm in Espoo. "
                   "Issue invoices, follow payments and prepare the monthly financial statements.",
        "tasks": [
            {"task": "Keep the books for 20 small business clients", "priority": "must_have",
             "skills": {"accounting": 3, "maintain financial records": 2}},
            {"task": "Issue sales invoices and follow up on payments", "priority": "must_have",
             "skills": {"issue sales invoices": 2}},
            {"task": "Prepare monthly financial statements for the clients", "priority": "learnable",
             "skills": {"prepare financial statements": 2}},
            {"task": "Use the firm's accounting software (Netvisor)", "priority": "learnable",
             "skills": {"use accounting systems": 1}},
        ],
        "flags": [],
    },
    {
        "id": "mock-job-08",
        "title": "Warehouse Worker (Forklift)",
        "summary": "Pick, pack and store goods in a grocery wholesaler's warehouse in Espoo. "
                   "Move pallets with a forklift and record the moves in the warehouse management system.",
        "tasks": [
            {"task": "Pick and pack customer orders for dispatch", "priority": "must_have",
             "skills": {"pick orders for dispatching": 3}},
            {"task": "Move pallets with a forklift between the dock and the racks", "priority": "must_have",
             "skills": {"operate forklift": 3}},
            {"task": "Receive and store incoming goods in the right places", "priority": "must_have",
             "skills": {"store warehouse goods": 2, "lift heavy weights": 1}},
            {"task": "Record picks and moves in the warehouse management system", "priority": "learnable",
             "skills": {"use a warehouse management system": 1}},
        ],
        "flags": [],
    },
    {
        "id": "mock-job-09",
        "title": "Logistics Coordinator",
        "summary": "Plan the daily deliveries of a building materials supplier and coordinate the transport partners. "
                   "Track shipments, keep stock records and report delivery times with spreadsheets.",
        "tasks": [
            {"task": "Plan daily delivery routes and book transport with partner carriers", "priority": "must_have",
             "skills": {"plan transport operations": 3, "coordinate transportation": 2}},
            {"task": "Track shipments and inform customers about delays", "priority": "must_have",
             "skills": {"track shipments": 2}},
            {"task": "Keep stock records of the two depots up to date", "priority": "learnable",
             "skills": {"keep stock records": 1, "supply chain management": 1}},
            {"task": "Report delivery times and costs in spreadsheets", "priority": "learnable",
             "skills": {"use spreadsheets software": 1}},
        ],
        "flags": [],
    },
    {
        "id": "mock-job-10",
        "title": "Practical Nurse (Elderly Care)",
        "summary": "Care for the residents of an assisted living home in Espoo in their daily activities. "
                   "Measure vital signs, help with medicines and give first aid when needed.",
        "tasks": [
            {"task": "Help residents with washing, dressing, eating and moving around", "priority": "must_have",
             "skills": {"tend to elderly people": 3, "provide basic support to patients": 2}},
            {"task": "Measure and record blood pressure, pulse and temperature", "priority": "must_have",
             "skills": {"monitor basic patients signs": 2}},
            {"task": "Help residents take their prescribed medicines", "priority": "learnable",
             "skills": {"assist in the administration of medication to elderly": 2}},
            {"task": "Give first aid in falls and other emergencies", "priority": "must_have",
             "skills": {"provide first aid": 1}},
        ],
        "flags": [],
    },
    {
        "id": "mock-job-11",
        "title": "Office Cleaner",
        "summary": "Clean offices, corridors and toilets in office buildings in Espoo's Keilaniemi area in the early morning. "
                   "Use floor cleaning machines and handle cleaning chemicals safely.",
        "tasks": [
            {"task": "Clean office floors, desks, kitchens and toilets", "priority": "must_have",
             "skills": {"clean building floors": 3, "clean toilet facilities": 2, "clean surfaces": 1}},
            {"task": "Use scrubber-dryers and other floor cleaning machines", "priority": "learnable",
             "skills": {"operate floor cleaning equipment": 2}},
            {"task": "Dose and store cleaning chemicals safely", "priority": "must_have",
             "skills": {"handle chemical cleaning agents": 2}},
        ],
        "flags": [],
    },
    {
        "id": "mock-job-12",
        "title": "Cook (School Kitchen)",
        "summary": "Cook lunch for about 300 pupils and staff in an Espoo school kitchen. "
                   "Follow food safety rules and help plan the weekly menu.",
        "tasks": [
            {"task": "Cook lunch for about 300 diners every school day", "priority": "must_have",
             "skills": {"use cooking techniques": 3, "cook meat dishes": 1, "cook vegetable products": 1}},
            {"task": "Follow food safety and hygiene rules and the self-monitoring plan", "priority": "must_have",
             "skills": {"comply with food safety and hygiene": 3}},
            {"task": "Use and clean the combi ovens and other kitchen equipment", "priority": "learnable",
             "skills": {"handle kitchen equipment": 1}},
            {"task": "Help plan the weekly menu, including special diets", "priority": "nice_to_have",
             "skills": {"plan menus": 1}},
        ],
        "flags": [],
    },
    {
        "id": "mock-job-13",
        "title": "Digital Marketing Coordinator",
        "summary": "Plan and run the social media campaigns of a regional sports retailer. "
                   "Write posts and newsletters, update the website and report the results.",
        "tasks": [
            {"task": "Plan and run campaigns on Instagram, Facebook and TikTok", "priority": "must_have",
             "skills": {"plan social media marketing campaigns": 3, "social media marketing techniques": 1}},
            {"task": "Write posts, product texts and the monthly newsletter", "priority": "must_have",
             "skills": {"create digital content": 2, "perform copywriting": 1}},
            {"task": "Track campaign results in Google Analytics and report them monthly", "priority": "learnable",
             "skills": {"web analytics": 2}},
            {"task": "Update product pages in the website's CMS", "priority": "learnable",
             "skills": {"use content management system software": 1}},
        ],
        "flags": [
            {"requirement": "Master's degree in marketing required",
             "concern": "The tasks are hands-on campaign and content work. A portfolio of campaigns shows the "
                        "skill better than a degree; consider dropping the degree requirement."},
        ],
    },
    {
        "id": "mock-job-14",
        "title": "Early Childhood Education Assistant",
        "summary": "Work in a team at an Espoo daycare centre with a group of 3-5 year olds. "
                   "Supervise and play with the children, help them with meals and dressing, and talk with parents.",
        "tasks": [
            {"task": "Supervise children indoors and in the yard", "priority": "must_have",
             "skills": {"supervise children": 3}},
            {"task": "Help children with meals, dressing and naps", "priority": "must_have",
             "skills": {"attend to children's basic physical needs": 2}},
            {"task": "Support children's play and learning in small groups", "priority": "must_have",
             "skills": {"assist children in developing personal skills": 2, "play with children": 1}},
            {"task": "Talk with parents at pick-up time in Finnish", "priority": "learnable",
             "skills": {"interact verbally in Finnish": 2}},
        ],
        "flags": [],
    },
    {
        "id": "mock-job-15",
        "title": "Electrician",
        "summary": "Install electrical systems in new apartment buildings in Espoo. "
                   "Read the electrical drawings, install wiring, sockets and lighting, and test the installations.",
        "tasks": [
            {"task": "Install wiring, sockets and lighting in new apartments", "priority": "must_have",
             "skills": {"install low voltage wiring": 3, "install electricity sockets": 1, "install lighting": 1}},
            {"task": "Read the electrical drawings of the building", "priority": "must_have",
             "skills": {"interpret electrical diagrams": 2}},
            {"task": "Test the installations and follow electrical safety rules", "priority": "must_have",
             "skills": {"test electrical equipment": 1, "comply with electrical safety regulations": 2}},
        ],
        "flags": [],
    },
]


# ---------- Applicants ----------
# (id, note, [(ESCO label, points, validation answer)]). The note is for developers only and is
# not stored. An empty answer means the applicant skipped the question.

APPLICANTS = [
    # --- Frontend developer (mock-job-01) ---
    ("mock-applicant-001", "job-01 strong fit (same skills, same priorities)", [
        ("JavaScript Framework", 3, "I built the booking calendar of a hair salon chain's web app in React, used by 40 salons."),
        ("JavaScript", 2, "I wrote a vanilla JavaScript widget that shows live bus times on a café's website."),
        ("TypeScript", 1, "I moved our team's React code from JavaScript to TypeScript, which caught a dozen hidden bugs."),
        ("debug software", 2, "A checkout page froze on Safari only; I traced it to a date parsing bug and fixed it the same day."),
        ("implement front-end website design", 2, "I turned Figma designs into responsive pages for a city event website."),
    ]),
    ("mock-applicant-002", "job-01 strong fit (same skills, other priorities)", [
        ("JavaScript", 4, "I have written JavaScript for six years, mostly interactive maps and forms."),
        ("implement front-end website design", 3, "I build accessible, responsive layouts from designers' mock-ups at a web agency."),
        ("JavaScript Framework", 1, "I have done one small Vue project and the official React tutorial."),
        ("debug software", 1, "I use the browser dev tools daily to find why a layout or script breaks."),
        ("TypeScript", 1, ""),
    ]),
    ("mock-applicant-003", "job-01 near fit (similar skills: web programming, ICT debugging tools)", [
        ("web programming", 4, "I built and maintain a small web shop for a bike repair shop with PHP and JavaScript."),
        ("JavaScript", 3, "I added a product filter and shopping cart in plain JavaScript to the same shop."),
        ("ICT debugging tools", 2, "I use Chrome DevTools and breakpoints to step through scripts when something fails."),
        ("create website wireframe", 1, "I sketched the wireframes for a sports club website before building it."),
    ]),
    ("mock-applicant-004", "job-01 partial fit, international (English only), bootcamp", [
        ("JavaScript Framework", 5, "In a coding bootcamp in Lisbon I built a React to-do app and a weather app as final projects."),
        ("JavaScript", 3, "I solved about 200 JavaScript exercises on an online platform during the bootcamp."),
        ("English", 2, "I worked in English in an international team for three years."),
    ]),
    ("mock-applicant-005", "job-01 career changer (graphic designer to frontend)", [
        ("graphic design", 4, "I designed brochures, logos and web layouts at a print house for eight years."),
        ("implement front-end website design", 3, "I started coding my own designs as HTML and CSS pages for small clients."),
        ("JavaScript", 2, "I am learning JavaScript and have added simple animations and form checks to my pages."),
        ("use markup languages", 1, ""),
    ]),

    # --- Backend developer (mock-job-02) ---
    ("mock-applicant-006", "job-02 strong fit (same skills, same priorities)", [
        ("Python (computer programming)", 3, "I wrote the Python backend for a parking app that handles 5,000 bookings a day."),
        ("SQL", 3, "I write PostgreSQL queries every day and once cut a report query from 30 seconds to 1."),
        ("debug software", 2, "I tracked down a timezone bug that double-booked rooms by reading the logs and adding a test."),
        ("design database scheme", 1, "I designed the tables for a new loyalty program, including migrations."),
        ("develop automated software tests", 1, "I wrote pytest tests for our API and raised coverage from 40% to 75%."),
    ]),
    ("mock-applicant-007", "job-02 strong fit (same skills, other priorities)", [
        ("SQL", 4, "I was the database person in a small team and wrote most of our reporting SQL."),
        ("Python (computer programming)", 3, "I build internal tools and small Flask APIs in Python."),
        ("debug software", 1, "I fix bugs in our internal tools when users report them."),
        ("design database scheme", 1, "I normalised an old customer database that had duplicates everywhere."),
        ("develop automated software tests", 1, ""),
    ]),
    ("mock-applicant-008", "job-02 near fit (Java instead of Python, PostgreSQL, data models)", [
        ("Java (computer programming)", 4, "I developed Spring Boot services for an insurance company for four years."),
        ("PostgreSQL", 2, "Our services stored their data in PostgreSQL and I wrote the migrations."),
        ("create data models", 2, "I modelled the data for a new claims handling service with the business analysts."),
        ("debug software", 2, "I found a memory leak in a production service by analysing heap dumps."),
    ]),
    ("mock-applicant-009", "job-02 partial fit, international (Russian, no Finnish)", [
        ("Python (computer programming)", 5, "I automated test data generation in Python at a software company in Saint Petersburg."),
        ("computer programming", 2, "I studied programming at university and wrote C and Python in my courses."),
        ("Russian", 3, "Russian is my first language and I worked in it for five years."),
    ]),
    ("mock-applicant-010", "job-02 career changer (mechanical engineer learning Python)", [
        ("mechanical engineering", 4, "I designed conveyor parts for a machine manufacturer for ten years."),
        ("Python (computer programming)", 3, "I wrote Python scripts that calculate load tables and saved our team hours every week."),
        ("solve problems", 3, "When a production line kept stopping, I measured, found a worn bearing pattern and fixed the design."),
    ]),

    # --- Data engineer (mock-job-03) ---
    ("mock-applicant-011", "job-03 strong fit (same skills, same priorities)", [
        ("data extraction, transformation and loading tools", 3, "I built Airflow pipelines that load ERP and web shop data into the warehouse every night."),
        ("data warehouse", 2, "I designed the star schema for sales reporting in our Snowflake warehouse."),
        ("SQL", 2, "I write complex SQL with window functions for the reporting tables."),
        ("perform data cleansing", 2, "I added checks that catch duplicate and missing customer ids before loading."),
        ("cloud technologies", 1, "We ran everything on AWS and I managed the S3 buckets and scheduled jobs."),
    ]),
    ("mock-applicant-012", "job-03 strong fit (same skills, other priorities)", [
        ("SQL", 4, "I have used SQL daily for five years as a BI developer."),
        ("Python (computer programming)", 3, "I write Python scripts with pandas to move and reshape data."),
        ("data extraction, transformation and loading tools", 1, "I maintained a few SSIS packages but did not build them."),
        ("data warehouse", 1, "I query our warehouse for reports."),
        ("cloud technologies", 1, ""),
    ]),
    ("mock-applicant-013", "job-03 near fit (similar skills: DataStage, data storage, query languages)", [
        ("IBM InfoSphere DataStage", 3, "I built DataStage jobs that load patient visit data into a hospital district's reporting database."),
        ("use query languages", 3, "I wrote queries in SQL and SPARQL for a research data portal."),
        ("data storage", 2, "I planned how our reporting data was partitioned and archived to keep queries fast."),
        ("manage data", 2, "I was responsible for the quality and documentation of a 20-year research data set."),
    ]),
    ("mock-applicant-014", "job-03 partial fit, international (Ukrainian), statistics graduate", [
        ("Python (computer programming)", 4, "I analysed survey data in Python for my master's thesis in Kyiv."),
        ("statistics", 3, "I ran regression models on labour market data at a research institute."),
        ("Ukrainian", 3, ""),
    ]),
    ("mock-applicant-015", "job-03 career changer (accountant moving to data)", [
        ("use spreadsheets software", 3, "I built Excel models with Power Query that combined data from four systems."),
        ("SQL", 3, "I taught myself SQL to pull invoice data directly from our ERP database."),
        ("accounting", 2, "I worked as an accountant for seven years."),
        ("perform data cleansing", 2, "I cleaned a supplier register of 12,000 rows with many duplicates before a system change."),
    ]),

    # --- Software tester (mock-job-04) ---
    ("mock-applicant-016", "job-04 strong fit (same skills, same priorities)", [
        ("execute software tests", 3, "I tested a mobile banking app on iOS and Android before every two-week release."),
        ("report test findings", 2, "My bug reports in Jira include steps, screenshots and logs, so developers can reproduce them fast."),
        ("plan software testing", 2, "I planned the tests for a new payments feature together with the product owner."),
        ("develop ICT test suite", 1, "I organised 300 test cases into suites for smoke and full regression testing."),
        ("develop automated software tests", 2, "I automated the login and transfer flows with Appium."),
    ]),
    ("mock-applicant-017", "job-04 strong fit (same skills, other priorities, automation-heavy)", [
        ("develop automated software tests", 4, "I wrote a Playwright test suite that runs 400 browser tests on every commit."),
        ("execute software tests", 2, "I do manual exploratory testing on new features before automating them."),
        ("plan software testing", 2, "I decide with the team which flows are worth automating."),
        ("report test findings", 1, ""),
        ("develop ICT test suite", 1, "I grouped our automated tests into fast and nightly suites."),
    ]),
    ("mock-applicant-018", "job-04 near fit (unit/integration testing, test documentation)", [
        ("perform software unit testing", 3, "As a junior developer I wrote unit tests for every function I changed."),
        ("execute integration testing", 3, "I tested how our web shop talked to the payment and stock systems before releases."),
        ("provide software testing documentation", 2, "I wrote the test reports that went to the customer at the end of each sprint."),
        ("levels of software testing", 2, "I took the ISTQB Foundation course and know the test levels from it."),
    ]),
    ("mock-applicant-019", "job-04 career changer (customer service to QA)", [
        ("customer service", 3, "I worked four years in a telecom company's customer service."),
        ("execute software tests", 3, "I tested new versions of our customer service tool and found many bugs before go-live."),
        ("report test findings", 2, "I wrote down exactly how to reproduce the errors customers told us about."),
        ("interact verbally in Finnish", 2, "I served customers in Finnish on the phone every day."),
    ]),
    ("mock-applicant-020", "job-04 partial fit, international (Arabic, English)", [
        ("debug software", 4, "I found and fixed bugs in a hotel booking system in Amman."),
        ("execute software tests", 3, "I tested the booking system's mobile app before releases."),
        ("English", 2, "I worked in English with an international development team."),
        ("Arabic", 1, ""),
    ]),

    # --- IT support (mock-job-05) ---
    ("mock-applicant-021", "job-05 strong fit (same skills, same priorities)", [
        ("provide ICT support", 3, "I worked two years in a school district's IT support helping teachers with laptops and accounts."),
        ("support ICT system users", 2, "I showed teachers how to use the new learning platform, one class at a time."),
        ("troubleshoot", 2, "A whole classroom lost Wi-Fi; I found a faulty access point and replaced it."),
        ("install software", 2, "I installed and updated software and operating systems on 200 laptops using an imaging tool."),
        ("ICT help platforms", 1, "I handled about 30 tickets a day in ServiceNow."),
    ]),
    ("mock-applicant-022", "job-05 strong fit (same skills, other priorities, hands-on)", [
        ("troubleshoot", 4, "I repair computers and phones for neighbours and family as a hobby."),
        ("install software", 2, "I set up laptops for a local association's new members."),
        ("install operating system", 2, "I have installed Linux and Windows on dozens of old computers."),
        ("provide ICT support", 2, ""),
    ]),
    ("mock-applicant-023", "job-05 near fit (online help, ICT troubleshooting, training)", [
        ("provide online help", 3, "I answered users' questions in the chat support of a software company."),
        ("perform ICT troubleshooting", 3, "I found network and server problems with ping, traceroute and logs."),
        ("hardware components", 2, "I build my own computers and know which parts fail most."),
        ("provide ICT system training", 2, "I trained 50 office workers to use Teams when the company moved to it."),
    ]),
    ("mock-applicant-024", "job-05 partial fit, international (Estonian)", [
        ("provide ICT support", 4, "I worked in an IT service desk in Tallinn for three years."),
        ("install software", 3, "I prepared new workstations with all the software employees needed."),
        ("Estonian", 3, "Estonian is my first language."),
    ]),
    ("mock-applicant-025", "job-05 career changer (military signals)", [
        ("use communication devices", 3, "In my military service I set up and maintained field radio and phone links."),
        ("troubleshoot", 3, "I found and fixed broken connections in field conditions, often at night."),
        ("hardware components", 2, "I replaced faulty parts in radio equipment."),
        ("lead a team", 2, "I led a signals team of six conscripts."),
    ]),

    # --- Customer service (mock-job-06) ---
    ("mock-applicant-026", "job-06 strong fit (same skills, same priorities)", [
        ("answer incoming calls", 2, "I answered about 60 calls a day in an insurance company's customer service."),
        ("respond to customers' inquiries", 3, "I answered questions about bills and contracts by phone, chat and email."),
        ("handle customer complaints", 2, "An angry customer had been billed twice; I apologised, refunded it and called back to confirm."),
        ("customer relationship management", 1, "I recorded every case in Salesforce."),
        ("interact verbally in Finnish", 2, "I served customers in Finnish every day."),
    ]),
    ("mock-applicant-027", "job-06 strong fit (same skills, other priorities, complaints specialist)", [
        ("handle customer complaints", 4, "I handled escalated complaints in a telecom company's second line."),
        ("interact verbally in Finnish", 3, "Finnish is my working language."),
        ("respond to customers' inquiries", 1, ""),
        ("answer incoming calls", 1, "I took calls when the queue was long."),
        ("customer relationship management", 1, "I kept customer notes up to date in the CRM."),
    ]),
    ("mock-applicant-028", "job-06 career changer (retail to customer service)", [
        ("assist customers", 3, "I helped customers find products and sizes in a sports store for five years."),
        ("handle complaints", 3, "I handled returns and complaints at the store's service desk."),
        ("contact customers", 2, "I called customers when their special orders arrived."),
        ("operate cash register", 2, "I worked at the cash register and closed the till in the evenings."),
    ]),
    ("mock-applicant-029", "job-06 near fit, international (English, Russian, no Finnish)", [
        ("respond to customers' inquiries", 4, "I answered customers' questions by email and chat for an online travel agency."),
        ("answer incoming calls", 2, "I took calls from travellers whose flights were cancelled."),
        ("English", 2, "I served customers in English."),
        ("Russian", 2, "I served Russian-speaking customers."),
    ]),
    ("mock-applicant-030", "job-06 partial fit, international (Arabic, learning Finnish)", [
        ("communicate with customers", 3, "I worked at the front desk of a hotel in Dubai."),
        ("answer incoming calls", 3, "I answered the hotel's reservation line."),
        ("understand spoken Finnish", 2, "I have studied Finnish for two years and understand everyday conversations."),
        ("Arabic", 2, ""),
    ]),

    # --- Bookkeeper (mock-job-07) ---
    ("mock-applicant-031", "job-07 strong fit (same skills, same priorities)", [
        ("accounting", 3, "I kept the books for 15 small companies at an accounting firm."),
        ("maintain financial records", 2, "I recorded purchase and sales invoices and bank transactions every week."),
        ("issue sales invoices", 2, "I sent monthly invoices for a cleaning company and chased late payments."),
        ("prepare financial statements", 2, "I prepared the monthly profit and loss reports for clients."),
        ("use accounting systems", 1, "I used Netvisor and Procountor daily."),
    ]),
    ("mock-applicant-032", "job-07 strong fit (same skills, other priorities)", [
        ("prepare financial statements", 4, "I prepared annual financial statements for small limited companies."),
        ("accounting", 3, "I studied accounting at a university of applied sciences."),
        ("use accounting systems", 1, ""),
        ("issue sales invoices", 1, "I invoiced customers in my summer job."),
        ("maintain financial records", 1, "I kept the receipts and records of my student association."),
    ]),
    ("mock-applicant-033", "job-07 near fit (bookkeeping regulations, accounting records)", [
        ("bookkeeping regulations", 3, "I know the Finnish Accounting Act from my studies and applied it as a trainee."),
        ("check accounting records", 3, "I checked that bank statements and the ledger matched at month end."),
        ("accounting entries", 2, "I posted entries for purchase invoices and salaries."),
        ("issue purchase orders", 2, "I issued purchase orders for office supplies and services."),
    ]),
    ("mock-applicant-034", "job-07 partial fit, informal (family shop)", [
        ("maintain financial records", 3, "I kept the records of my family's grocery shop for six years."),
        ("handle financial transactions", 3, "I handled the shop's cash, card payments and bank deposits."),
        ("operate cash register", 2, "I worked at the shop's cash register."),
        ("sell products", 2, ""),
    ]),
    ("mock-applicant-035", "job-07 near-strong fit, international (Vietnamese)", [
        ("accounting", 4, "I worked as an accountant in a trading company in Hanoi for five years."),
        ("prepare financial statements", 3, "I prepared quarterly financial statements under local rules."),
        ("perform balance sheet operations", 1, "I prepared the balance sheet reconciliations each quarter."),
        ("Vietnamese", 2, ""),
    ]),

    # --- Warehouse worker (mock-job-08) ---
    ("mock-applicant-036", "job-08 strong fit (same skills, same priorities)", [
        ("pick orders for dispatching", 3, "I picked about 150 order lines an hour in a grocery warehouse."),
        ("operate forklift", 3, "I have a forklift licence and moved pallets daily for three years."),
        ("store warehouse goods", 2, "I received deliveries and put goods in the right rack locations."),
        ("use a warehouse management system", 1, "I used a handheld scanner with the warehouse system for every pick."),
        ("lift heavy weights", 1, "I lifted boxes of up to 25 kg all day."),
    ]),
    ("mock-applicant-037", "job-08 strong fit (same skills, forklift-heavy)", [
        ("operate forklift", 5, "I drove counterbalance and reach trucks for eight years without an accident."),
        ("store warehouse goods", 2, "I stored goods on high racks with the reach truck."),
        ("pick orders for dispatching", 1, ""),
        ("use a warehouse management system", 1, ""),
        ("lift heavy weights", 1, ""),
    ]),
    ("mock-applicant-038", "job-08 near fit (lifting equipment, warehousing operations)", [
        ("operate lifting equipment", 4, "I operated pallet stackers and a small crane at a building materials yard."),
        ("load heavy items on pallets", 2, "I loaded cement bags and tiles onto pallets for customer orders."),
        ("perform warehousing operations", 2, "I did receiving, storing and inventory counts in the yard's warehouse."),
        ("dispatch order processing", 2, "I prepared orders for the delivery trucks every morning."),
    ]),
    ("mock-applicant-039", "job-08 partial fit, international (Ukrainian)", [
        ("pick orders for dispatching", 4, "I picked orders in a parcel warehouse near Lviv."),
        ("lift heavy weights", 3, "I lifted and carried parcels all day."),
        ("Ukrainian", 3, ""),
    ]),
    ("mock-applicant-040", "job-08 career changer (military logistics, drivers)", [
        ("drive vehicles", 3, "I drove trucks in the army and have a C licence."),
        ("operate lifting equipment", 2, "I used a forklift and a truck crane to load supplies in the army."),
        ("military drill", 2, "I completed 12 months of military service."),
        ("lead a team", 3, "I led a supply squad of eight conscripts."),
    ]),

    # --- Logistics coordinator (mock-job-09) ---
    ("mock-applicant-041", "job-09 strong fit (same skills, same priorities)", [
        ("plan transport operations", 3, "I planned daily delivery routes for 20 trucks at a building materials supplier."),
        ("coordinate transportation", 2, "I booked transport from five carriers and solved clashes when trucks were late."),
        ("track shipments", 2, "I tracked shipments in the carriers' systems and called customers about delays."),
        ("keep stock records", 2, "I updated stock records after every delivery."),
        ("use spreadsheets software", 1, "I built a weekly delivery report in Excel."),
    ]),
    ("mock-applicant-042", "job-09 strong fit (same skills, other priorities)", [
        ("track shipments", 4, "I followed up international shipments for an import company."),
        ("use spreadsheets software", 3, "I made pivot tables and charts of delivery times for management."),
        ("coordinate transportation", 1, ""),
        ("plan transport operations", 1, "I sometimes planned deliveries when the planner was away."),
        ("supply chain management", 1, ""),
    ]),
    ("mock-applicant-043", "job-09 near fit (logistics, fleet, cargo operations)", [
        ("logistics", 3, "I studied logistics and did my internship in a port operator's office."),
        ("manage logistics", 3, "I organised the logistics of a music festival with 30,000 visitors as a volunteer."),
        ("coordinate transport fleet", 2, "I scheduled a fleet of 12 vans for a home delivery company."),
        ("plan procedures for cargo operations", 2, "I planned loading orders for container ships during my internship."),
    ]),
    ("mock-applicant-044", "job-09 career changer (military logistics)", [
        ("plan transport operations", 3, "As a logistics officer in the defence forces I planned the transport of supplies for exercises."),
        ("coordinate transportation", 2, "I coordinated trucks, trains and units so that supplies arrived on time."),
        ("lead a team", 2, "I led a transport platoon."),
        ("drive vehicles", 2, ""),
        ("military drill", 1, "I served as a career soldier for nine years."),
    ]),
    ("mock-applicant-045", "job-09 partial fit, international (Estonian, Russian truck driver)", [
        ("drive vehicles", 4, "I drove international routes between Tallinn, Riga and Warsaw for six years."),
        ("track shipments", 2, "I reported my shipments' status to the dispatcher in the tracking app."),
        ("Estonian", 2, ""),
        ("Russian", 2, ""),
    ]),

    # --- Practical nurse (mock-job-10) ---
    ("mock-applicant-046", "job-10 strong fit (same skills, same priorities)", [
        ("tend to elderly people", 3, "I worked three years in an Espoo assisted living home helping residents with daily care."),
        ("provide basic support to patients", 2, "I helped residents wash, dress and move safely with a lift."),
        ("monitor basic patients signs", 2, "I measured blood pressure and blood sugar and recorded them in the patient system."),
        ("assist in the administration of medication to elderly", 2, "I handed out medicines from the dose dispensers and checked they were taken."),
        ("provide first aid", 1, "A resident fell and hit their head; I gave first aid and called the nurse."),
    ]),
    ("mock-applicant-047", "job-10 strong fit (same skills, other priorities, clinical focus)", [
        ("monitor basic patients signs", 4, "I measured vital signs on a hospital ward and noticed early when a patient got worse."),
        ("provide first aid", 3, "I have a valid first aid certificate and have used it twice."),
        ("tend to elderly people", 1, ""),
        ("provide basic support to patients", 1, ""),
        ("assist in the administration of medication to elderly", 1, "I handed out medicines under a nurse's supervision."),
    ]),
    ("mock-applicant-048", "job-10 near fit, international (nurse trained abroad, English)", [
        ("monitor patient's health condition", 3, "I monitored post-surgery patients in a hospital in Manila for four years."),
        ("older adults' needs", 3, "I cared for elderly patients with dementia on a geriatric ward."),
        ("assist with self-medication", 2, "I helped patients learn to take their own medicines before discharge."),
        ("first aid", 1, "I am trained in basic life support."),
        ("English", 1, "I worked in English in the hospital."),
    ]),
    ("mock-applicant-049", "job-10 career changer (cleaner to care work)", [
        ("clean rooms", 3, "I cleaned residents' rooms in a care home for four years."),
        ("tend to elderly people", 3, "Residents often asked me for help, and I started helping the carers with meals and walks."),
        ("show empathy", 2, "I took time to chat with lonely residents during my cleaning rounds."),
        ("maintain personal hygiene standards when cleaning", 2, ""),
    ]),
    ("mock-applicant-050", "job-10 partial fit, informal (family carer, volunteer)", [
        ("tend to elderly people", 4, "I cared for my grandparent at home for three years, including washing and medicines."),
        ("show empathy", 3, "I volunteer weekly as a visitor for lonely elderly people through a church group."),
        ("interact verbally in Finnish", 3, ""),
    ]),
    ("mock-applicant-051", "job-10 partial fit, international (Arabic, learning Finnish)", [
        ("provide basic support to patients", 3, "I worked as a nursing assistant in a hospital in Baghdad."),
        ("take and analyse blood pressure", 2, "I measured patients' blood pressure several times a day."),
        ("understand spoken Finnish", 3, "I am taking a Finnish course for healthcare workers."),
        ("Arabic", 2, ""),
    ]),

    # --- Office cleaner (mock-job-11) ---
    ("mock-applicant-052", "job-11 strong fit (same skills, same priorities)", [
        ("clean building floors", 3, "I cleaned the floors of a 6-floor office building every morning for two years."),
        ("clean toilet facilities", 2, "I cleaned and restocked 20 toilets daily."),
        ("clean surfaces", 1, "I wiped desks, kitchens and meeting rooms."),
        ("operate floor cleaning equipment", 2, "I used a scrubber-dryer in the lobby and corridors."),
        ("handle chemical cleaning agents", 2, "I dosed cleaning chemicals according to the safety data sheets."),
    ]),
    ("mock-applicant-053", "job-11 strong fit (same skills, machine-heavy)", [
        ("operate floor cleaning equipment", 4, "I operated ride-on scrubbers in a shopping centre at night."),
        ("handle chemical cleaning agents", 3, "I was trained to use and store strong floor stripping chemicals."),
        ("clean building floors", 1, ""),
        ("clean toilet facilities", 1, ""),
        ("clean surfaces", 1, ""),
    ]),
    ("mock-applicant-054", "job-11 near fit (public areas, rooms, chemicals)", [
        ("clean public areas", 3, "I cleaned the waiting halls of a railway station."),
        ("clean rooms", 3, "I cleaned guest rooms in a hotel."),
        ("maintain cleaning equipment", 2, "I cleaned and checked our machines and mops at the end of every shift."),
        ("handle chemicals", 2, "I worked with chemicals in a car wash."),
    ]),
    ("mock-applicant-055", "job-11 partial fit, international (Persian)", [
        ("clean surfaces", 4, "I cleaned offices in Tehran for five years."),
        ("clean rooms", 3, "I cleaned private homes as a second job."),
        ("Persian", 3, ""),
    ]),
    ("mock-applicant-056", "job-11 partial fit, international (Spanish, hotel housekeeping)", [
        ("clean rooms", 4, "I cleaned 16 hotel rooms per shift in a hotel in Barcelona."),
        ("clean toilet facilities", 2, "I cleaned the bathrooms of every room."),
        ("work in teams", 2, "We worked in pairs and shared the floors fairly."),
        ("Spanish", 2, ""),
    ]),

    # --- Cook (mock-job-12) ---
    ("mock-applicant-057", "job-12 strong fit (same skills, same priorities)", [
        ("use cooking techniques", 3, "I cooked lunch for 400 people a day in a company restaurant."),
        ("cook meat dishes", 1, "I made meatballs and stews in batches of 50 kg."),
        ("cook vegetable products", 2, "I cooked the vegetarian option every day."),
        ("comply with food safety and hygiene", 3, "I have the Finnish hygiene passport and kept the self-monitoring records."),
        ("handle kitchen equipment", 1, "I used combi ovens and tilting pans."),
    ]),
    ("mock-applicant-058", "job-12 strong fit (same skills, other priorities, menu planner)", [
        ("plan menus", 4, "I planned the four-week menu of a daycare kitchen including allergy diets."),
        ("use cooking techniques", 2, "I trained as a cook at a vocational school."),
        ("comply with food safety and hygiene", 2, "I followed the kitchen's self-monitoring plan."),
        ("cook meat dishes", 1, ""),
        ("cook vegetable products", 1, ""),
    ]),
    ("mock-applicant-059", "job-12 near fit (food preparation, HACCP, reheating)", [
        ("use food preparation techniques", 4, "I prepared salads and side dishes in a lunch restaurant."),
        ("prepare ready-made dishes", 2, "I made ready meals for a grocery store's deli counter."),
        ("apply HACCP", 2, "I did the temperature checks and records in the deli."),
        ("use reheating techniques", 2, "I reheated and served meals in a hospital ward kitchen."),
    ]),
    ("mock-applicant-060", "job-12 partial fit, informal (home cook, community volunteer)", [
        ("use cooking techniques", 4, "I cook for 80 people at our community centre's monthly dinner as a volunteer."),
        ("cook vegetable products", 3, "I cook mostly vegetarian food from many cuisines."),
        ("plan menus", 3, "I plan the dinners and shopping lists for the community centre."),
    ]),
    ("mock-applicant-061", "job-12 near-strong fit, international (Chinese)", [
        ("use cooking techniques", 4, "I worked as a line cook in a restaurant in Guangzhou for seven years."),
        ("comply with food safety and hygiene", 3, ""),
        ("cook seafood", 1, "I prepared fish and seafood dishes every day."),
        ("Chinese", 2, ""),
    ]),

    # --- Digital marketing (mock-job-13) ---
    ("mock-applicant-062", "job-13 strong fit (same skills, same priorities)", [
        ("plan social media marketing campaigns", 3, "I planned a spring campaign for a sports store that doubled its Instagram sales."),
        ("create digital content", 2, "I made videos and posts for TikTok and Instagram every week."),
        ("perform copywriting", 1, "I wrote the product texts and the monthly newsletter."),
        ("web analytics", 2, "I reported campaign results from Google Analytics each month."),
        ("use content management system software", 2, "I updated product pages in WordPress."),
    ]),
    ("mock-applicant-063", "job-13 strong fit (same skills, content-heavy)", [
        ("create digital content", 4, "I run a hiking blog and YouTube channel with 10,000 followers."),
        ("perform copywriting", 3, "I write ads and web texts as a freelancer."),
        ("plan social media marketing campaigns", 1, ""),
        ("web analytics", 1, "I follow my blog's visitors in Google Analytics."),
        ("use content management system software", 1, "My blog runs on WordPress."),
    ]),
    ("mock-applicant-064", "job-13 near fit (digital marketing, digital content, business analytics)", [
        ("plan digital marketing", 3, "I made the yearly digital marketing plan for a small software company."),
        ("develop digital content", 3, "I produced webinars and blog posts for the same company."),
        ("business analytics", 2, "I built dashboards on leads and sales in Power BI."),
        ("social media management", 2, "I managed the company's LinkedIn and Facebook pages."),
    ]),
    ("mock-applicant-065", "job-13 partial fit, international (English, French)", [
        ("plan social media marketing campaigns", 3, "I ran campaigns for a fashion brand in Paris."),
        ("create digital images", 3, "I shot and edited product photos for Instagram."),
        ("English", 2, ""),
        ("French", 2, ""),
    ]),
    ("mock-applicant-066", "job-13 career changer (retail to marketing)", [
        ("sell products", 3, "I worked as a sales assistant in a sports store for four years."),
        ("social media marketing techniques", 3, "I started the store's Instagram account and grew it to 3,000 followers."),
        ("photography", 2, "I photograph products and events as a hobby."),
        ("assist customers", 2, ""),
    ]),

    # --- Early childhood education assistant (mock-job-14) ---
    ("mock-applicant-067", "job-14 strong fit (same skills, same priorities)", [
        ("supervise children", 3, "I worked two years as a substitute in Espoo daycare centres."),
        ("attend to children's basic physical needs", 2, "I helped children with eating, dressing and naps every day."),
        ("assist children in developing personal skills", 2, "I ran a small group that practised taking turns and naming feelings."),
        ("play with children", 1, "I organised yard games for the 4-year-olds."),
        ("interact verbally in Finnish", 2, "I talked with parents in Finnish at pick-up time."),
    ]),
    ("mock-applicant-068", "job-14 strong fit (same skills, play-focused)", [
        ("play with children", 4, "I worked at a play park and organised games every day."),
        ("assist children in developing personal skills", 3, "I coached children's crafts clubs and saw shy children open up."),
        ("supervise children", 1, ""),
        ("attend to children's basic physical needs", 1, ""),
        ("interact verbally in Finnish", 1, ""),
    ]),
    ("mock-applicant-069", "job-14 near fit (safeguarding, wellbeing, kindergarten teaching)", [
        ("contribute to the safeguarding of children", 3, "I noticed signs of neglect in a child and reported them following the procedure."),
        ("support children's wellbeing", 3, "I ran calm-down corners and feelings activities in an after-school club."),
        ("teach kindergarten class content", 2, "I taught colours, numbers and songs to 5-year-olds."),
        ("understand spoken Finnish", 2, ""),
    ]),
    ("mock-applicant-070", "job-14 partial fit, international (kindergarten teacher, Ukrainian)", [
        ("teach kindergarten class content", 4, "I was a kindergarten teacher in Kharkiv for ten years."),
        ("supervise children", 2, "I was responsible for a group of 20 children, indoors and on outings."),
        ("Ukrainian", 2, ""),
        ("English", 2, "I can work in English while I learn Finnish."),
    ]),
    ("mock-applicant-071", "job-14 partial fit, informal (volunteer scout leader, sports coach)", [
        ("supervise children", 3, "I lead a scout group of 15 children every week as a volunteer."),
        ("play with children", 3, "I plan games for our scout evenings and summer camps."),
        ("coaching techniques", 2, "I coach a junior football team."),
        ("provide first aid", 2, "I have a first aid certificate for the camps."),
    ]),

    # --- Electrician (mock-job-15) ---
    ("mock-applicant-072", "job-15 strong fit (same skills, same priorities)", [
        ("install low voltage wiring", 3, "I installed wiring in new apartment buildings for four years."),
        ("install electricity sockets", 2, "I installed sockets, switches and lights in about 300 apartments."),
        ("interpret electrical diagrams", 2, "I work from the electrical drawings every day."),
        ("test electrical equipment", 1, "I do the commissioning measurements and fill in the test reports."),
        ("comply with electrical safety regulations", 2, "I hold a Finnish electrical safety (SFS 6002) card."),
    ]),
    ("mock-applicant-073", "job-15 strong fit (same skills, other priorities)", [
        ("interpret electrical diagrams", 4, "I studied as an electrical technician and read diagrams better than I install."),
        ("comply with electrical safety regulations", 3, "I follow the safety rules strictly and checked them for my team."),
        ("install low voltage wiring", 1, ""),
        ("install electricity sockets", 1, ""),
        ("install lighting", 1, ""),
    ]),
    ("mock-applicant-074", "job-15 near fit (switches, power lines, wiring diagrams)", [
        ("install electric switches", 3, "I installed switchgear and switches in industrial buildings."),
        ("install power lines", 3, "I worked on overhead and underground power line projects."),
        ("electrical wiring diagrams", 2, "I drew simple wiring diagrams for small renovations."),
        ("electrical safety regulations", 2, "I know the safety rules and have the safety card."),
    ]),
    ("mock-applicant-075", "job-15 near-strong fit, international (Estonian)", [
        ("install low voltage wiring", 4, "I worked as an electrician on building sites in Tallinn."),
        ("maintain electrical equipment", 3, "I maintained electrical systems in an apartment complex."),
        ("Estonian", 3, ""),
    ]),
    ("mock-applicant-076", "job-15 career changer (military engineer)", [
        ("repair wiring", 3, "I repaired wiring in military vehicles and field generators."),
        ("maintain electrical equipment", 3, "I maintained the power supply of a field camp."),
        ("military drill", 2, ""),
        ("use power tools", 2, "I used power tools daily in engineering work."),
    ]),

    # --- No fit for any mock job ---
    ("mock-applicant-077", "no fit (musician)", [
        ("play musical instruments", 5, "I play the cello in a chamber orchestra and teach private lessons."),
        ("perform dances", 3, "I dance in a folk dance group that performs at festivals."),
        ("English", 2, ""),
    ]),
    ("mock-applicant-078", "no fit (photographer)", [
        ("photography", 5, "I photograph weddings and events as a freelancer."),
        ("operate a camera", 3, "I shoot video for local businesses with a cinema camera."),
        ("create digital images", 2, "I edit and retouch all my photos myself."),
    ]),
    ("mock-applicant-079", "no fit (translator, international)", [
        ("translate texts", 6, "I translated technical manuals from Russian to Finnish for ten years."),
        ("Russian", 2, ""),
        ("Finnish", 2, "I passed the national language certificate at the highest level."),
    ]),
    ("mock-applicant-080", "no fit (gardener)", [
        ("prune hedges and trees", 5, "I pruned trees and hedges for a landscaping company for six seasons."),
        ("prune plants", 3, "I take care of the plants of a city park as a summer worker."),
        ("use hand tools", 2, ""),
    ]),
    ("mock-applicant-081", "no fit (plasterer)", [
        ("plaster surfaces", 5, "I plastered walls in renovation projects for eight years."),
        ("prepare surface for plastering", 3, "I prepared old walls by cleaning and priming them."),
        ("use power tools", 2, "I use mixers, sanders and drills every day."),
    ]),
    ("mock-applicant-082", "no fit (dog breeder and groomer)", [
        ("breed dogs", 4, "I have bred a small dog breed for twelve years."),
        ("groom animals", 4, "I groom dogs in my own salon."),
        ("show empathy", 2, ""),
    ]),
    ("mock-applicant-083", "no fit (military combat background, no transferable skills chosen)", [
        ("military combat techniques", 4, "I served in an infantry unit for six years."),
        ("military weaponry", 4, "I was responsible for the maintenance of the unit's weapons."),
        ("lead a team", 2, "I led a squad of eight soldiers."),
    ]),
    ("mock-applicant-084", "no fit (language teacher, international)", [
        ("teach languages", 5, "I taught Spanish and German at a language school in Madrid."),
        ("Spanish", 3, ""),
        ("German", 2, ""),
    ]),
    ("mock-applicant-085", "no fit (hairdresser)", [
        ("style hair", 6, "I worked as a hairdresser in a salon for nine years."),
        ("hairdressing", 4, ""),
    ]),
    ("mock-applicant-086", "no fit (dairy farm worker)", [
        ("milk animals", 4, "I milked 60 cows twice a day on a dairy farm."),
        ("breed cattle", 3, "I took care of calving and the breeding records."),
        ("drive vehicles", 3, "I drive tractors and farm vehicles."),
    ]),
]


# ---------- Resolving labels ----------

def load_meta():
    return json.loads(META_PATH.read_text(encoding="utf-8"))["skills"]


def all_labels():
    labels = []
    for job in JOBS:
        for task in job["tasks"]:
            labels += list(task["skills"])
    for _, _, skills in APPLICANTS:
        labels += [label for label, _, _ in skills]
    return labels


def resolve_labels(meta):
    """{label: skill meta}. Exits with suggestions if any label is not an exact ESCO label."""
    by_label = {}
    for s in meta:
        by_label.setdefault(s["label"], {})[s["uri"]] = s
    unknown = sorted({l for l in all_labels() if l not in by_label})
    ambiguous = sorted({l for l in all_labels() if len(by_label.get(l, {})) > 1})
    if unknown or ambiguous:
        lines = []
        if unknown:
            from search import SkillIndex
            index = SkillIndex()
            for label in unknown:
                hits = index.search(label, k=5)
                lines.append(f"  unknown: {label!r} -> try: " + " | ".join(h["label"] for h in hits))
        for label in ambiguous:
            lines.append(f"  ambiguous (several URIs): {label!r}")
        sys.exit("Labels that are not exact ESCO labels:\n" + "\n".join(lines))
    return {l: next(iter(uris.values())) for l, uris in by_label.items()}


# ---------- Building profiles ----------

def build_job(job, skills):
    tasks, required = [], []
    for t in job["tasks"]:
        tasks.append(Task(task=t["task"], priority=t["priority"], source="mock", skills=list(t["skills"])))
        for label, points in t["skills"].items():
            s = skills[label]
            required.append(RequiredSkill(uri=s["uri"], label=s["label"], skillType=s["skillType"],
                                          priority=t["priority"], points=points, tasks=[t["task"]]))
    try:
        return JobProfile(title=job["title"], summary=job["summary"], tasks=tasks,
                          flags=[Flag(**f) for f in job["flags"]], skills=required)
    except ValueError as e:
        sys.exit(f"{job['id']}: {e}")


def build_applicant(applicant_id, claims, skills, questions):
    """Built through make_applicant_profile, so only the top-points skills (skills_to_validate)
    keep their question and answer; the other hand-written answers are ignored."""
    confirmed = [{"uri": skills[label]["uri"], "label": label, "skillType": skills[label]["skillType"],
                  "origin": "added" if label in LANGUAGES else "suggested"} for label, _, _ in claims]
    allocation = {skills[label]["uri"]: points for label, points, _ in claims}
    answers = {skills[label]["uri"]: answer for label, _, answer in claims}
    try:
        return make_applicant_profile(confirmed, allocation, questions, answers)
    except ValueError as e:
        sys.exit(f"{applicant_id}: {e}")


def check_ids():
    ids = [j["id"] for j in JOBS] + [a[0] for a in APPLICANTS]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        sys.exit(f"duplicate ids: {sorted(dupes)}")
    bad = [i for i in ids if not i.startswith(MOCK_PREFIX)]
    if bad:
        sys.exit(f"ids must start with {MOCK_PREFIX!r}: {bad}")


def get_questions(applicant_skills, meta):
    """Validation questions for every applicant skill, via ApplicantFlow.questions_for().
    Uses the shared cache; uncached skills are generated by Gemini in batches."""
    from applicant import ApplicantFlow, _load_cache

    cache = _load_cache()
    missing = [s for s in applicant_skills if f"English|{s['uri']}" not in cache]
    if missing and not os.environ.get("GEMINI_API_KEY"):
        sys.exit(f"{len(missing)} skills have no cached validation question and GEMINI_API_KEY is not set.")
    if missing:
        flow = ApplicantFlow()
    else:
        # Everything is cached, so no Gemini client is needed: questions_for() only reads the index.
        flow = ApplicantFlow(mapper=SimpleNamespace(index=SimpleNamespace(skills=meta)))
    questions = {}
    batch = 40
    for i in range(0, len(applicant_skills), batch):
        questions.update(flow.questions_for(applicant_skills[i:i + batch]))
    return questions


# ---------- Database ----------

def clear_mock(conn):
    with conn:
        jobs = conn.execute("DELETE FROM jobs WHERE id LIKE ?", (MOCK_PREFIX + "%",)).rowcount
        applicants = conn.execute("DELETE FROM applicants WHERE id LIKE ?", (MOCK_PREFIX + "%",)).rowcount
    return jobs, applicants


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clear", action="store_true", help="only delete all mock-* jobs and applicants")
    parser.add_argument("--check", action="store_true", help="only resolve labels and validate, no database writes")
    args = parser.parse_args()

    import db

    if args.clear:
        conn = db.connect()
        jobs, applicants = clear_mock(conn)
        conn.close()
        print(f"Deleted {jobs} mock jobs and {applicants} mock applicants.")
        return

    check_ids()
    meta = load_meta()
    skills = resolve_labels(meta)
    jobs = {j["id"]: build_job(j, skills) for j in JOBS}

    applicant_uris = list(dict.fromkeys(skills[l]["uri"] for _, _, claims in APPLICANTS for l, _, _ in claims))
    if args.check:
        questions = {}
    else:
        questions = get_questions([{"uri": u} for u in applicant_uris], meta)
    applicants = {aid: build_applicant(aid, claims, skills, questions) for aid, _, claims in APPLICANTS}
    if args.check:
        print(f"OK: {len(jobs)} jobs and {len(applicants)} applicants are valid.")
        return

    conn = db.connect()
    cleared = clear_mock(conn)
    for job_id, job in jobs.items():
        db.save_job(conn, job, job_id=job_id)
    for applicant_id, profile in applicants.items():
        db.save_applicant(conn, profile, applicant_id=applicant_id)
    conn.close()
    print(f"Replaced {cleared[0]} jobs and {cleared[1]} applicants with "
          f"{len(jobs)} mock jobs and {len(applicants)} mock applicants in {db.DB_PATH}.")


if __name__ == "__main__":
    main()

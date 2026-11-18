import os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Ensure output directory exists
os.makedirs("data", exist_ok=True)
excel_path = os.path.join("data", "ai_python_fresher_jobs_blr_hyd.xlsx")
csv_path = os.path.join("data", "ai_python_fresher_jobs_blr_hyd.csv")

jobs = [
    {
        "id": 1,
        "company": "Sarvam AI",
        "role": "Associate AI / Agent Engineer",
        "domain": "Generative AI & Indic LLMs",
        "location": "Bengaluru",
        "experience": "0-1 Years (Freshers / Batch 2024-2025)",
        "degree": "B.Tech / M.Tech / MS in CS, AI, or Data Science",
        "key_skills": "Python, PyTorch, LLMs, RAG Pipelines, Prompt Engineering, FastAPI, Vector DBs (Chroma/Pinecone)",
        "job_description": "Build autonomous agents, integrate foundational LLM APIs, optimize inference pipelines, and implement retrieval-augmented generation (RAG) for multilingual enterprise applications.",
        "salary_range": "₹8 - ₹14 LPA (Competitive Startup Package)",
        "apply_link": "https://sarvam.ai/careers"
    },
    {
        "id": 2,
        "company": "Yellow.ai",
        "role": "SDE Intern / Junior Python Developer",
        "domain": "Conversational & Agentic AI",
        "location": "Bengaluru",
        "experience": "0-1 Years (Freshers / Intern-to-Hire)",
        "degree": "B.E / B.Tech / MCA in Computer Science / IT",
        "key_skills": "Python, FastAPI / Flask, Data Structures & Algorithms, RESTful APIs, Git, Docker, LLM Orchestration",
        "job_description": "Develop high-throughput backend services and bot-building tooling, integrate conversational AI agents, and write clean asynchronous Python APIs.",
        "salary_range": "₹35,000 - ₹50,000/mo (Intern) -> ₹7 - ₹11 LPA (FTE)",
        "apply_link": "https://careers.yellow.ai"
    },
    {
        "id": 3,
        "company": "Darwinbox",
        "role": "Software Engineering Intern / Associate Backend Developer",
        "domain": "AI-Native Enterprise HR Tech (Unicorn)",
        "location": "Hyderabad",
        "experience": "0-1 Years (2024 / 2025 Graduates)",
        "degree": "B.Tech / B.E in CS / IT / ECE (65%+ aggregate)",
        "key_skills": "Python, OOP concepts, MySQL / PostgreSQL, REST API Architecture, Data Structures, Redis",
        "job_description": "Work with core engineering teams to scale HCM cloud microservices, develop automated workflows, and build AI-assisted decision systems for enterprise HR workflows.",
        "salary_range": "₹30,000 - ₹45,000/mo (Intern) -> ₹6.5 - ₹10 LPA (FTE)",
        "apply_link": "https://darwinbox.com/careers"
    },
    {
        "id": 4,
        "company": "Cognida.ai",
        "role": "Junior AI / RAG Engineer",
        "domain": "Enterprise AI Solutions & Databricks Integration",
        "location": "Hyderabad",
        "experience": "0-1 Years (Freshers welcome)",
        "degree": "B.Tech / M.Tech in CS / AI / Data Science",
        "key_skills": "Python, LangChain, LlamaIndex, RAG Architecture, Vector Databases, Databricks, REST APIs",
        "job_description": "Design and benchmark enterprise RAG applications, construct document ingestion and embedding pipelines, and integrate generative AI assistants for business data.",
        "salary_range": "₹5 - ₹8 LPA",
        "apply_link": "https://cognida.keka.com/careers"
    },
    {
        "id": 5,
        "company": "Pixis",
        "role": "Associate AI Software Engineer",
        "domain": "Contextual AI for Marketing Automation",
        "location": "Bengaluru (HSR Layout)",
        "experience": "0-1 Years (Strong project portfolio)",
        "degree": "B.Tech / M.Tech in Computer Science / Mathematics",
        "key_skills": "Python, PyTorch / TensorFlow, FastAPI, Model Quantization/Serving (ONNX/TensorRT), Docker",
        "job_description": "Engineer scalable AI systems backing the Prism marketing intelligence suite, deploy machine learning models behind fast microservices, and optimize real-time inference.",
        "salary_range": "₹8 - ₹12 LPA",
        "apply_link": "https://pixis.ai"
    },
    {
        "id": 6,
        "company": "Keka HR",
        "role": "Python Developer Intern / Junior Backend Developer",
        "domain": "SaaS Platform & Automation",
        "location": "Hyderabad",
        "experience": "0-1 Years (Freshers)",
        "degree": "B.Tech / B.E / MCA in CS/IT",
        "key_skills": "Python, Django / Flask, PostgreSQL, REST APIs, JSON/AsyncIO, Celery, Git",
        "job_description": "Build high-reliability backend endpoints, optimize SQL queries, implement asynchronous task queues for payroll processing, and develop reporting integrations.",
        "salary_range": "₹25,000 - ₹40,000/mo (Intern) -> ₹5.5 - ₹9 LPA (FTE)",
        "apply_link": "https://www.keka.com/careers"
    },
    {
        "id": 7,
        "company": "Sigmoid Analytics",
        "role": "Associate Data & AI Engineer (SYGP)",
        "domain": "Data Engineering & AI Consultancy",
        "location": "Bengaluru",
        "experience": "0-1 Years (Sigmoid Young Graduate Program)",
        "degree": "B.Tech / B.E in CS / IT / Math / Stats (60%+ throughout)",
        "key_skills": "Python, PySpark, Advanced SQL, Data Pipelines (ETL/ELT), AWS/GCP Basics, Machine Learning Concepts",
        "job_description": "Participate in the Takshashila training program, build scalable cloud data pipelines, perform feature engineering, and support predictive and AI models in production.",
        "salary_range": "₹6.5 - ₹9.5 LPA",
        "apply_link": "https://www.sigmoid.com/careers"
    },
    {
        "id": 8,
        "company": "HighRadius",
        "role": "Associate Software Engineer - Python & AI Services",
        "domain": "Autonomous Finance & AI SaaS",
        "location": "Hyderabad",
        "experience": "0-1 Years (Freshers / Campus / Off-campus)",
        "degree": "B.Tech / B.E / M.Tech in CS/IT",
        "key_skills": "Python 3.x, Flask, RESTful APIs, OOP, PostgreSQL / MySQL, Unit Testing, Linux",
        "job_description": "Develop and maintain microservices powering autonomous finance workflows, write unit tests, integrate intelligent pattern-recognition algorithms, and optimize database schemas.",
        "salary_range": "₹6 - ₹9 LPA",
        "apply_link": "https://careers.highradius.com"
    },
    {
        "id": 9,
        "company": "Inkers Technology",
        "role": "Junior Computer Vision & AI Engineer",
        "domain": "Vision AI & Edge Computing",
        "location": "Bengaluru",
        "experience": "0-1 Years (Freshers with hands-on projects)",
        "degree": "B.Tech / M.Tech in CS, Electronics, or AI",
        "key_skills": "Python, OpenCV, PyTorch, CNNs, Object Detection (YOLO), Linux, Edge AI (Jetson/ONNX)",
        "job_description": "Train and deploy deep learning models for industrial computer vision, optimize neural network inference on edge hardware, and write camera streaming pipelines in Python.",
        "salary_range": "₹5 - ₹8 LPA",
        "apply_link": "https://inkers.ai"
    },
    {
        "id": 10,
        "company": "Hasura",
        "role": "Software Engineering Intern / Associate Backend Engineer",
        "domain": "Developer Tooling & GraphQL Data Engines",
        "location": "Bengaluru (Hybrid/Remote)",
        "experience": "0-1 Years (Freshers with OSS contributions)",
        "degree": "B.Tech / B.E in Computer Science or self-taught equivalent",
        "key_skills": "Python, PostgreSQL, GraphQL/REST APIs, Docker, Data Structures, Git, Distributed Systems Basics",
        "job_description": "Build connectors and developer tooling for automated GraphQL and REST APIs, write integration tests in Python, benchmark latency, and contribute to developer docs and SDKs.",
        "salary_range": "₹40,000 - ₹60,000/mo (Intern) -> ₹10 - ₹16 LPA (FTE)",
        "apply_link": "https://hasura.io/careers"
    }
]

# Create Workbook
wb = Workbook()

# Sheet 1: Job Openings
ws1 = wb.active
ws1.title = "Job Openings"

# Styling definitions
font_title = Font(name="Segoe UI", size=15, bold=True, color="FFFFFF")
font_header = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
font_body = Font(name="Segoe UI", size=10, color="222222")
font_link = Font(name="Segoe UI", size=10, color="0056B3", underline="single")

fill_title = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
fill_header = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
fill_zebra = PatternFill(start_color="F2F5F9", end_color="F2F5F9", fill_type="solid")
fill_white = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")

thin_border = Side(style='thin', color='D9D9D9')
border_cell = Border(left=thin_border, right=thin_border, top=thin_border, bottom=thin_border)

# Title Banner
ws1.merge_cells("A1:J1")
title_cell = ws1["A1"]
title_cell.value = "Top 10 AI Engineer & Python Developer Fresher Job Openings (Bengaluru & Hyderabad Startups)"
title_cell.font = font_title
title_cell.fill = fill_title
title_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
ws1.row_dimensions[1].height = 40

# Headers
headers = [
    "No.",
    "Company Name",
    "Role Title",
    "Location",
    "Startup Focus / Domain",
    "Eligibility / Experience",
    "Eligible Degrees",
    "Key Required Skills",
    "Salary / Stipend Estimate",
    "Direct Application / Career Link"
]

ws1.append([]) # row 2 blank
ws1.append(headers) # row 3
ws1.row_dimensions[3].height = 28

for col_idx in range(1, len(headers) + 1):
    cell = ws1.cell(row=3, column=col_idx)
    cell.font = font_header
    cell.fill = fill_header
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

# Data Rows
current_row = 4
for item in jobs:
    ws1.append([
        item["id"],
        item["company"],
        item["role"],
        item["location"],
        item["domain"],
        item["experience"],
        item["degree"],
        item["key_skills"],
        item["salary_range"],
        item["apply_link"]
    ])
    ws1.row_dimensions[current_row].height = 55
    fill_row = fill_zebra if item["id"] % 2 == 0 else fill_white
    
    for col_idx in range(1, 11):
        c = ws1.cell(row=current_row, column=col_idx)
        c.border = border_cell
        c.fill = fill_row
        
        if col_idx == 1:
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.font = font_body
        elif col_idx in (2, 3, 4):
            c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            c.font = Font(name="Segoe UI", size=10, bold=(col_idx == 2), color="222222")
        elif col_idx == 10:
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.font = font_link
            c.hyperlink = item["apply_link"]
        else:
            c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            c.font = font_body

    current_row += 1

# Column Widths for Sheet 1
col_widths = {
    "A": 6,   # No
    "B": 18,  # Company
    "C": 28,  # Role
    "D": 15,  # Location
    "E": 26,  # Domain
    "F": 25,  # Experience
    "G": 28,  # Degree
    "H": 36,  # Skills
    "I": 24,  # Salary
    "J": 30   # Link
}
for col_letter, width in col_widths.items():
    ws1.column_dimensions[col_letter].width = width


# Sheet 2: Required Skills Analysis
ws2 = wb.create_sheet(title="Skill Analysis")

ws2.merge_cells("A1:E1")
s2_title = ws2["A1"]
s2_title.value = "Market Skills Analysis for AI & Python Fresher Roles (2025/2026 Batch)"
s2_title.font = font_title
s2_title.fill = PatternFill(start_color="385723", end_color="385723", fill_type="solid")
s2_title.alignment = Alignment(horizontal="center", vertical="center")
ws2.row_dimensions[1].height = 40

s2_headers = ["Skill Category", "Key Technologies & Frameworks", "Industry Demand %", "Why Startups Value This", "Recommended Fresher Project / Proof-of-Work"]
ws2.append([])
ws2.append(s2_headers)
ws2.row_dimensions[3].height = 28

for col_idx in range(1, len(s2_headers) + 1):
    cell = ws2.cell(row=3, column=col_idx)
    cell.font = font_header
    cell.fill = PatternFill(start_color="4F6228", end_color="4F6228", fill_type="solid")
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

skills_analysis_data = [
    (
        "Core Programming",
        "Python 3.10+, OOP, Data Structures & Algorithms, Asynchronous Programming (asyncio), Type Hinting",
        "100%",
        "Primary foundation across both AI modeling and backend services.",
        "LeetCode / Codeforces problem solving; CLI utilities with robust test suites."
    ),
    (
        "Backend & API Frameworks",
        "FastAPI, Flask, Django, Pydantic, RESTful APIs, WebSockets",
        "90%",
        "Startups require engineers to expose AI models as production-ready web APIs.",
        "FastAPI microservice with Swagger docs, JWT authentication, and rate limiting."
    ),
    (
        "Generative AI & LLMs",
        "LangChain, LangGraph, LlamaIndex, OpenAI / Anthropic APIs, Ollama, Hugging Face Transformers",
        "85%",
        "Every modern tech startup is incorporating generative AI into customer or internal workflows.",
        "Autonomous multi-step agent or RAG pipeline querying documents with vector retrieval."
    ),
    (
        "Vector Databases & RAG",
        "ChromaDB, Pinecone, FAISS, pgvector, Qdrant",
        "80%",
        "Grounding LLMs with proprietary company knowledge base and eliminating hallucinations.",
        "End-to-end PDF / Knowledge Base QA bot with semantic search and reranking."
    ),
    (
        "Databases & Storage",
        "PostgreSQL, MySQL, Redis, MongoDB, SQLAlchemy / Alembic",
        "85%",
        "Data persistence for user chats, metadata, sessions, and transaction processing.",
        "Relational schema design with migration scripts and caching layer using Redis."
    ),
    (
        "Deep Learning & Vision (Niche)",
        "PyTorch, OpenCV, YOLO, Torchvision, ONNX Runtime",
        "50%",
        "Crucial for computer vision, robotics, and edge AI product startups.",
        "Real-time object detection or defect classification pipeline running on video streams."
    ),
    (
        "DevOps & Deployment",
        "Docker, Git/GitHub, Linux commands, CI/CD Actions, AWS / GCP Basics",
        "75%",
        "Startups operate lean teams where developers deploy and maintain their own containers.",
        "Dockerized repository with GitHub Actions CI pipeline and deployment to cloud/Render."
    )
]

r_idx = 4
for row in skills_analysis_data:
    ws2.append(list(row))
    ws2.row_dimensions[r_idx].height = 45
    fill_row = fill_zebra if r_idx % 2 == 0 else fill_white
    for c_idx in range(1, 6):
        c = ws2.cell(row=r_idx, column=c_idx)
        c.border = border_cell
        c.fill = fill_row
        c.font = font_body
        if c_idx == 3:
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.font = Font(name="Segoe UI", size=10, bold=True, color="1F4E79")
        elif c_idx == 1:
            c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            c.font = Font(name="Segoe UI", size=10, bold=True, color="222222")
        else:
            c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    r_idx += 1

ws2.column_dimensions["A"].width = 24
ws2.column_dimensions["B"].width = 38
ws2.column_dimensions["C"].width = 16
ws2.column_dimensions["D"].width = 34
ws2.column_dimensions["E"].width = 42


# Sheet 3: City & Startup Ecosystem Insights
ws3 = wb.create_sheet(title="Ecosystem Comparison")

ws3.merge_cells("A1:D1")
s3_title = ws3["A1"]
s3_title.value = "Bengaluru vs Hyderabad: AI & Python Hiring Ecosystem for Freshers"
s3_title.font = font_title
s3_title.fill = PatternFill(start_color="833C0C", end_color="833C0C", fill_type="solid")
s3_title.alignment = Alignment(horizontal="center", vertical="center")
ws3.row_dimensions[1].height = 40

s3_headers = ["Parameter", "Bengaluru (Silicon Valley of India)", "Hyderabad (Cyberabad)", "Actionable Strategy for Freshers"]
ws3.append([])
ws3.append(s3_headers)
ws3.row_dimensions[3].height = 28

for col_idx in range(1, len(s3_headers) + 1):
    cell = ws3.cell(row=3, column=col_idx)
    cell.font = font_header
    cell.fill = PatternFill(start_color="A61C1C", end_color="A61C1C", fill_type="solid")
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

eco_data = [
    (
        "Startup Concentration",
        "Highest density of early-stage, seed, and Series-A AI product startups (Koramangala, HSR Layout, Indiranagar).",
        "Strong concentration of growth-stage SaaS unicorns (Darwinbox, Keka, HighRadius, Zenoti) in Hitec City & Gachibowli.",
        "Bengaluru has more early-stage AI agent startups; Hyderabad has mature SaaS scaleups hiring structured batches."
    ),
    (
        "Hiring Channels",
        "Wellfound, Twitter/X tech communities, YC startup networks, Cutshort, and direct founder outreach.",
        "Keka Careers, company portals, direct university/off-campus pool drives, LinkedIn jobs, and local recruiters.",
        "For Bengaluru, DM founders with GitHub demo links; for Hyderabad, apply through careers pages and employee referrals."
    ),
    (
        "Fresher Compensation",
        "₹6 LPA to ₹15 LPA depending on funding stage and AI depth; high equity grant potential.",
        "₹5 LPA to ₹11 LPA; often includes stable structured bonus, training allowance, and clear promotion ladders.",
        "Target internships that convert to PPOs (Pre-Placement Offers) after 3-6 months."
    ),
    (
        "Evaluation Focus",
        "Speed of shipping, working GitHub proof-of-work (RAG/agents), hackathon wins, fast learning.",
        "Strong fundamentals in Data Structures, Database design (SQL), OOP, and clean Python backend code.",
        "Prepare dual track: LeetCode Mediums + 1 polished GenAI project with live deployed demo."
    )
]

r_idx = 4
for row in eco_data:
    ws3.append(list(row))
    ws3.row_dimensions[r_idx].height = 55
    fill_row = fill_zebra if r_idx % 2 == 0 else fill_white
    for c_idx in range(1, 5):
        c = ws3.cell(row=r_idx, column=c_idx)
        c.border = border_cell
        c.fill = fill_row
        c.font = font_body
        if c_idx == 1:
            c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            c.font = Font(name="Segoe UI", size=10, bold=True, color="222222")
        else:
            c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    r_idx += 1

ws3.column_dimensions["A"].width = 24
ws3.column_dimensions["B"].width = 38
ws3.column_dimensions["C"].width = 38
ws3.column_dimensions["D"].width = 40

# Save Workbook
wb.save(excel_path)
print(f"Successfully generated Excel report at {excel_path}")

# Also generate clean CSV file
import csv
with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(headers)
    for j in jobs:
        writer.writerow([
            j["id"],
            j["company"],
            j["role"],
            j["location"],
            j["domain"],
            j["experience"],
            j["degree"],
            j["key_skills"],
            j["salary_range"],
            j["apply_link"]
        ])
print(f"Successfully generated CSV report at {csv_path}")

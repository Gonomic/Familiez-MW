from datetime import datetime
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from typing import List
from pydantic import BaseModel

origins = ["http://localhost:5174", "http://localhost", "http://127.0.0.1:8000","http://localhost:3310"]


def row2dict(row):
    return {column: value for column, value in row.items()}

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL= "mysql+pymysql://HumansService:XHHxECL54EjvhhPSBLMU@familiez-test-be/humans"

@app.get("/")
def read_root():
    return {"Hello visitor": "The Familiez Fastapi api lives!"}

@app.get("/pingAPI")
def ping_api(timestampFE: datetime):
    # return {"PingResultFromApi": "Ok", "Timestamp": {"FE request time": timestampFE, "MW request time": datetime.now()}}
    return [{"FE request time": timestampFE, "MW request time": datetime.now()}]

@app.get("/pingDB")
def ping_db(timestampFE: datetime):
    engine = create_engine(DATABASE_URL)
    timestampMWrequest= datetime.now()
    with engine.connect() as connection:
        results_proxy=connection.execute(
            text("call PingedDbServer(:timestampFErequest, :timestampMWrequest)"),
            {"timestampFErequest": timestampFE.strftime('%Y-%m-%d %H:%M:%S.%f'), "timestampMWrequest": timestampMWrequest.strftime('%Y-%m-%d %H:%M:%S.%f')})
        results = results_proxy.fetchall()
        result = [row._asdict() for row in results]
        result[-1]['datetimeMWanswer'] = datetime.now()
    return result

@app.get("/GetPersonsLike")
def get_persons_like(stringToSearchFor: str = Query(..., description="(Part of)Name to search for")):
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        results_proxy=connection.execute(
            text("call GetPersonsLike(:stringToSearchFor)"), {"stringToSearchFor": stringToSearchFor})
        results = results_proxy.fetchall()
        result=[]
        if len(results) == 0: 
            result.append({'numberOfRecords': 0})
        else: 
            result.append({'numberOfRecords': len(results)})
            result.extend([row._asdict() for row in results])
    return result

@app.get("/GetSiblings")
def get_siblings(parentID: int = Query(..., description="Person ID of the father to lookup the childs for")):
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        results_proxy=connection.execute(
            text("call GetAllChildrenWithoutPartnerFromOneParent(:ParentIdToSearchFor)"), {"ParentIdToSearchFor": parentID})
        results = results_proxy.fetchall()
        result=[]
        if len(results) == 0: 
            result.append({'numberOfRecords': 0})
        else: 
            result.append({'numberOfRecords': len(results)})
            result.extend([row._asdict() for row in results])
    return result


@app.get("/GetFather")
def get_father(childID: int = Query(..., description="Person ID of the child to lookup the father for")):
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        results_proxy=connection.execute(
            text("call GetFather(:childId)"), {"childId": childID})
        results = results_proxy.fetchall()
        result=[]
        if len(results) == 0: 
            result.append({'numberOfRecords': 0})
        else: 
            result.append({'numberOfRecords': len(results)})
            result.extend([row._asdict() for row in results])
    return result
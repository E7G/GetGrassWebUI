# 当前路径加入系统变量 ------------------------------------
import os
import sys
root_path = os.getcwd()
# print(root_path)
sys.path.append(root_path)
# -----------------------------------------------------


import asyncio
import uuid

import uvicorn
from typing import Dict, Optional

from fastapi import FastAPI, APIRouter, UploadFile, BackgroundTasks
from fastapi.templating import Jinja2Templates
from loguru import logger
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.staticfiles import StaticFiles

from utils import parse_line
from core import AsyncGrassWs

app = FastAPI()

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

client_router = APIRouter(prefix='/client')

all_client: Dict[str, AsyncGrassWs] = {}
all_client_ids = []

CLIENT_INDEX = 0

# 或者，如果有多个 task
background_tasks = set()


def run_client(client_id):
    task = asyncio.create_task(all_client[client_id].run())

    # 将 task 添加到集合中，以保持强引用：
    background_tasks.add(task)

    # 为了防止 task 被永远保持强引用，而无法被垃圾回收
    # 让每个 task 在结束后将自己从集合中移除：
    task.add_done_callback(background_tasks.discard)
    return client_id


def add_client(grass_client: AsyncGrassWs):
    client_id = uuid.uuid4().__str__()
    all_client[client_id] = grass_client
    all_client_ids.append(client_id)
    save_client_info(client_id, grass_client.user_id, grass_client.proxy_url)  # Save client info to file
    return client_id


async def delete_client(client_id):
    logger.info(f'[退出] {all_client[client_id].user_id}')
    await all_client[client_id].stop()
    del all_client[client_id]
    all_client_ids.remove(client_id)


def load_file_clients(data):
    new_clients = []
    index = 0
    for line in data.split('\n'):
        user_id, proxy_url = parse_line(line)
        if not user_id:
            continue
        index += 1
        client = AsyncGrassWs(user_id=user_id, proxy_url=proxy_url)
        new_client_id = add_client(client)
        new_clients.append(new_client_id)
    return new_clients


async def threading_run_clients(clients):
    for client_id in clients:
        run_client(client_id)


def check_existing_user(user_id):
    with open("accounts.txt", "r") as file:
        return any(user_id in line for line in file)

def save_client_info(client_id, user_id, proxy_url):
    # Check if proxy_url is None
    if proxy_url is not None:
        # Check if the user_id already exists in the file
        if check_existing_user(user_id):
            print(f"User with ID {user_id} already exists in the file.")
            return

        # Open the file in append mode
        with open("accounts.txt", "a") as file:
            # Write user_id and proxy_url to the file
            file.write(f"{user_id}=={proxy_url}\n")
    else:
        # Check if the user_id already exists in the file
        if check_existing_user(user_id):
            print(f"User with ID {user_id} already exists in the file.")
            return

        # Open the file in append mode
        with open("accounts.txt", "a") as file:
            # Write only user_id to the file
            file.write(f"{user_id}\n")



@app.get("/", response_class=HTMLResponse)
async def read_item(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@client_router.get("/{client_id}")
def find_one(client_id: str):
    client = all_client.get(client_id)
    data = {
        'data': {
            'status': None,
            "proxy_url": None,
            "logs": []
        },
        'message': "failed"
    }
    if client is not None:
        data = {
            'data': {
                'status': client.status,
                "proxy_url": client.proxy_url,
                "logs": list(reversed(client.logs[-50:]))
            },
            'message': "success"
        }
    return data


@client_router.get("/")
def find_all():
    data = []
    for client_id in all_client_ids:
        try:
            data.append({
                'id': client_id,
                'user_id': all_client[client_id].user_id,
                'status': all_client[client_id].status,
                "proxy_url": all_client[client_id].proxy_url
            })
        except:
            continue
    return {
        'data': data,
        'message': "success"
    }


@client_router.post("/")
async def add(user_id: str, proxy_url: Optional[str] = None):
    client = AsyncGrassWs(user_id=user_id, proxy_url=proxy_url or None)
    client_id = add_client(client)
    run_client(client_id)
    return {'data': client_id, 'message': 'create success'}


@client_router.delete("/{user_id}")
async def delete_one(user_id: str):
    await delete_client(user_id)
    return {'data': user_id, 'message': 'success'}


@client_router.delete("/")
async def delete_all():
    all_client_ids_copy = all_client_ids[::]
    for client_id in all_client_ids_copy:
        await delete_client(client_id)
    return {'data': [], 'message': 'success'}


@app.post("/upload/")
async def run_by_file(file: UploadFile, background_task: BackgroundTasks):
    data = (await file.read()).decode()
    new_clients = load_file_clients(data)
    background_task.add_task(threading_run_clients, new_clients)
    return {"data": None, 'message': 'success'}


app.include_router(client_router)

# Check if the accounts.txt file exists or is empty and take appropriate action

import os

async def init_load():
    if not os.path.exists("accounts.txt") or os.stat("accounts.txt").st_size == 0:
        # Handle the case when accounts.txt doesn't exist or is empty
        # For example, you can create a default entry or display a message
        print("No client accounts found in the file.")
    else:
        # Continue with the normal flow
        with open("accounts.txt", "r") as file:
            data = file.read()
            new_clients = load_file_clients(data)
            await threading_run_clients(new_clients)

@app.on_event("startup")
async def startup_event():
    # 在这里，你可以在应用程序启动时运行代码
    print("FastAPI 应用程序已启动")
    await init_load()


import socket
from contextlib import closing

def get_free_port():
    """ Get free port"""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s: 
        s.bind(('', 0)) 
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) 
        return s.getsockname()[1] 
    

if __name__ == '__main__':
    uvicorn.run("main:app", host='0.0.0.0',port=get_free_port())

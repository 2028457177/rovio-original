import os
import hashlib
import pandas as pd
from AIRAGAgent.utils.logger_handler import logger
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader,TextLoader

def get_file_md5_hex(filepath:str):     # 获取文件的md5的十六进制字符串
    """计算文件的MD5十六进制字符串（分块读取，大文件也适用）。"""
    if not os.path.exists(filepath):
        logger.error(f"[md5计算]文件{filepath}不存在")
        return

    if not os.path.isfile(filepath):
        logger.error(f"[md5计算]路径{filepath}不是文件")
        return

    md5_obj = hashlib.md5()

    chunk_size = 4096       # 每次读取4KB
    try:
        with open(filepath, "rb") as f:     #必须二进制读取
            while chunk := f.read(chunk_size):
                md5_obj.update(chunk)
                md5_hex = md5_obj.hexdigest()
                # return md5_hex
            return md5_hex
    except Exception as e:
        logger.error(f"[md5计算]文件{filepath}计算失败,错误信息:{str(e)}")
        return  None


def listdir_with_allowed_type(path: str, allowed_types: tuple[str]):        #返回文件夹内的文件列表(允许的文件后缀)
    """返回文件夹内后缀名符合 allowed_types 的文件路径列表（元组）。"""
    files = []

    if not os.path.isdir(path):
        logger.error(f"[listdir_with_allowed_type]{path}不是文件夹")
        return allowed_types

    for f in os.listdir(path):
        if f.endswith(allowed_types):
            files.append(os.path.join(path, f))

    return  tuple(files)


def pdf_loader(filepath: str, passwd=None) -> list[Document]:
    """加载PDF文件并返回Document文档列表。"""
    return PyPDFLoader(filepath, passwd).load()


def txt_loader(filepath: str)-> list[Document]:
    """按UTF-8编码加载TXT文本文件并返回Document文档列表。"""
    return TextLoader(filepath,encoding="utf-8").load()


# 加载excel文件
def excel_loader(filepath: str)-> list[Document]:
    documents = []
    try:
        # 读取Excel文件的所有工作表
        xls = pd.ExcelFile(filepath)
        for sheet_name in xls.sheet_names:
            # 读取工作表数据
            df = pd.read_excel(xls, sheet_name=sheet_name)
            # 将数据转换为字符串
            content = df.to_string(index=False)
            # 创建Document对象
            doc = Document(
                page_content=content,
                metadata={"source": filepath, "sheet_name": sheet_name}
            )
            documents.append(doc)
    except Exception as e:
        logger.error(f"[Excel加载]文件{filepath}加载失败,错误信息:{str(e)}")
    return documents
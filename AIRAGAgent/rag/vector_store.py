import os
from os.path import split

from langchain_chroma import Chroma
from langchain_core.documents import Document
from AIRAGAgent.utils.config_handler import chroma_conf
from AIRAGAgent.model.factory import embed_model
from langchain_text_splitters import RecursiveCharacterTextSplitter
from AIRAGAgent.utils.path_tool import get_abs_path
from AIRAGAgent.utils.file_handler import pdf_loader,txt_loader,excel_loader,listdir_with_allowed_type,get_file_md5_hex
from AIRAGAgent.utils.logger_handler import logger

# 向量数据库服务类
class VectorStoreService:
    """
    向量数据库服务类
    """
    # 初始化向量数据库
    def __init__(self):
        # 初始化向量数据库
        self.vector_store = Chroma(
            collection_name=chroma_conf["collection_name"],     # 向量数据库集合名
            embedding_function=embed_model,                 # 在线嵌入模型
            persist_directory=chroma_conf["persist_directory"],     # 持久化目录
        )
        # 初始化文本分割器
        self.spliter = RecursiveCharacterTextSplitter(
            chunk_size=chroma_conf["chunk_size"],     # 文本分割器分块大小
            chunk_overlap=chroma_conf["chunk_overlap"],     # 文本分割器分块重叠大小
            separators=chroma_conf["separators"],     # 文本分割器分隔符
            length_function=len,     # 文本分割器长度函数
        )
        
        # 初始化时加载文档
        self.load_document()    # 加载文档

    # 获取检索器
    def get_retriever(self):
        return self.vector_store.as_retriever(search_kwargs={"k": chroma_conf["k"]})

    # 加载文档
    def load_document(self):
        """
        从数据文件夹内读取数据文件，转为向量存入向量库
        要计算文件的MD5做去重
        :return: None
        """
        def check_md5_hex(md5_for_check:str):
            """检查 MD5 是否已记录在去重文件中（已记录返回 True），文件缺失时自动创建并返回 False。"""
            if not os.path.exists(get_abs_path(chroma_conf["md5_hex_store"])):
                open(get_abs_path(chroma_conf["md5_hex_store"]), "w", encoding="utf-8").close()
                return  False

            with open(get_abs_path(chroma_conf["md5_hex_store"]), encoding="utf-8") as f:
                for line in f.readlines():
                    line = line.strip()
                    if line == md5_for_check:
                        return True


                return  False

        # 保存md5
        def save_md5_hex(md5_for_check:str):
            """把md5值追加写入配置指定的md5存储文件。"""
            with open(get_abs_path(chroma_conf["md5_hex_store"]), "a", encoding="utf-8") as f:
                f.write(md5_for_check + "\n")


        def get_file_doucuments(read_path:str):
            """按文件后缀（txt/pdf/xlsx）加载对应格式的文档列表。"""
            if read_path.endswith(".txt"):
                return txt_loader(read_path)
            if read_path.endswith(".pdf"):
                return pdf_loader(read_path)
            if read_path.endswith(".xlsx"):
                return excel_loader(read_path)
            return []

        allowed_file_path: list[str] = listdir_with_allowed_type(
            get_abs_path(chroma_conf["data_path"]),
            tuple(chroma_conf["allow_knowledge_file_type"]),
        )
        for path in allowed_file_path:
            md5_hex = get_file_md5_hex(path)

            if check_md5_hex(md5_hex):
                logger.info(f"[加载知识库]{path}内容已经存在知识库内，跳过")
                continue

            try:
                documents: list[Document] = get_file_doucuments(path)

                if not documents:
                    logger.warning(f"[加载知识库]{path}没有有效文本，跳过")
                    continue

                split_document: list[Document] = self.spliter.split_documents(documents)

                if not split_document:
                    logger.warning(f"[加载知识库]{path}分片后没有有效文本，跳过")
                    continue

                #将内容存入向量库
                self.vector_store.add_documents(split_document)

                # 记录这个已经处理好的文件的md5，避免下次重复加载
                save_md5_hex(md5_hex)

                logger.info(f"[加载知识库]{path}内容加载成功")
            except Exception as e:
                #exc_1nto为True会记录详细的报错堆栈，如果为Fa1se仅记录报错信息本身
                logger.error(f"[加载知识库]{path}内容加载失败:{str(e)}",exc_info=True)
                continue



if __name__ == '__main__':
    vs = VectorStoreService()

    vs.load_document()

    retriever = vs.get_retriever()

    res = retriever.invoke("迷路")
    for r in res:
        print(r.page_content)
        print("-"*20)

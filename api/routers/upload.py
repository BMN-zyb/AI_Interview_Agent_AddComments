"""
文件上传路由
POST /upload/resume  -> 解析 PDF/Word/TXT，返回文本内容
"""
# 启用延迟注解求值（PEP 563），类型注解以字符串保存，便于前向引用与兼容性。
from __future__ import annotations

# 标准库 io：将上传得到的字节内容包装为内存中的二进制流，供解析库读取。
import io

# FastAPI：路由器、文件上传声明（File/UploadFile）与 HTTP 异常类型。
from fastapi import APIRouter, File, HTTPException, UploadFile
# loguru：日志库，记录上传与解析过程。
from loguru import logger

# 上传接口的响应数据模型（Pydantic），约束返回结构。
from api.schemas import UploadResponse

# 创建上传路由器：统一加 /upload 前缀，并在文档中归入“文件上传”分组。
router = APIRouter(prefix="/upload", tags=["文件上传"])


# 注册 POST /upload/resume 接口，响应体须符合 UploadResponse。
# File(...) 表示该参数为必传的上传文件。
@router.post("/resume", response_model=UploadResponse)
async def upload_resume(file: UploadFile = File(...)):
    """
    上传简历文件（PDF / DOCX / TXT），返回提取的纯文本

    参数:
        file: 上传的简历文件对象。
    返回:
        UploadResponse: 包含文件名、提取出的文本及字符数。
    """
    # 取文件名（缺失时回退为空字符串），用于后续按扩展名分派解析方式。
    filename = file.filename or ""
    # 异步读取整个上传文件的原始字节内容。
    content  = await file.read()
    # 预置提取结果文本为空字符串。
    text     = ""

    try:
        # 按扩展名选择对应解析器：PDF。
        if filename.endswith(".pdf"):
            text = _extract_pdf(content)
        # Word 文档（.docx/.doc）。
        elif filename.endswith((".docx", ".doc")):
            text = _extract_docx(content)
        # 纯文本/Markdown：直接以 UTF-8 解码，忽略无法解码的字节。
        elif filename.endswith((".txt", ".md")):
            text = content.decode("utf-8", errors="ignore")
        # 其它格式不支持：返回 400 提示可用格式。
        else:
            raise HTTPException(
                status_code=400,
                detail="不支持的文件格式，请上传 PDF / DOCX / TXT",
            )
    # 已是 HTTPException（如上面的 400 或解析器内抛出的异常），原样向上抛出，
    # 避免被下方的通用异常分支吞掉并改写为 500。
    except HTTPException:
        raise
    # 其它未预期异常：记录日志并统一返回 500。
    except Exception as e:
        logger.error("简历解析失败: {}", e)
        raise HTTPException(status_code=500, detail=f"文件解析失败: {e}")

    # 解析结果为空（去除空白后无内容）：返回 422 表示内容不可解析。
    if not text.strip():
        raise HTTPException(status_code=422, detail="文件内容为空，无法解析")

    # 记录上传成功日志：文件名与提取出的字符数。
    logger.info("简历上传成功: {} {} 字符", filename, len(text))
    # 返回响应：文件名、提取文本及字符数。
    return UploadResponse(
        filename=filename,     # 原始文件名
        text=text,             # 提取出的纯文本
        char_count=len(text),  # 文本字符数
    )


def _extract_pdf(content: bytes) -> str:
    """从 PDF 字节内容中提取纯文本。

    参数:
        content: PDF 文件的原始字节。
    返回:
        逐页提取并以换行拼接后的文本。
    异常:
        HTTPException(500): 当 pypdf 依赖未安装时抛出。
    """
    try:
        # 延迟导入 pypdf：仅在确有 PDF 需要解析时才依赖该库。
        from pypdf import PdfReader
        # 以内存字节流构造 PDF 读取器。
        reader = PdfReader(io.BytesIO(content))
        # 逐页提取文本（某页可能返回 None，用 "" 兜底），再以换行拼接成整篇文本。
        return "\n".join(
            page.extract_text() or "" for page in reader.pages
        )
    except ImportError:
        # 依赖缺失：返回 500 提示安装 pypdf。
        raise HTTPException(status_code=500, detail="pypdf 未安装，无法解析 PDF")


def _extract_docx(content: bytes) -> str:
    """从 Word(.docx) 字节内容中提取纯文本。

    参数:
        content: DOCX 文件的原始字节。
    返回:
        逐段落提取并以换行拼接后的文本。
    异常:
        HTTPException(500): 当 python-docx 依赖未安装时抛出。
    """
    try:
        # 延迟导入 python-docx（模块名为 docx）。
        import docx
        # 以内存字节流构造 Word 文档对象。
        doc = docx.Document(io.BytesIO(content))
        # 取出全部段落文本并以换行拼接。
        return "\n".join(p.text for p in doc.paragraphs)
    except ImportError:
        # 依赖缺失：返回 500 提示安装 python-docx。
        raise HTTPException(status_code=500, detail="python-docx 未安装，无法解析 DOCX")
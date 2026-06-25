"""
engines.document_engine — 文档格式转换引擎

- convert_pdf_to_docx: PDF → DOCX（pdf2docx，纯 Python）
- convert_docx_to_pdf: DOCX → PDF（docx2pdf / pywin32 COM）
"""


__all__ = ['convert_pdf_to_docx', 'convert_docx_to_pdf']

import os
from utils import finalize_file
from engines._common import _prepare_output


def convert_pdf_to_docx(input_path: str, output_path: str) -> str:
    """
    PDF → DOCX 转换（pdf2docx 实现）。
    纯 Python 实现，无需 Microsoft Word。
    """
    from pdf2docx import Converter

    temp_path = _prepare_output(output_path)

    try:
        cv = Converter(input_path)
        cv.convert(temp_path, start=0, end=None)
        cv.close()
    except Exception as e:
        raise RuntimeError(f'PDF 转换失败: {e}')

    finalize_file(temp_path, output_path)
    return output_path


def convert_docx_to_pdf(input_path: str, output_path: str) -> str:
    """
    DOCX → PDF 转换（docx2pdf / pywin32 COM 自动化）。

    必须 try...except 捕获 COM 异常（如本地未安装 Word），
    返回友好的中文错误字符串，绝不闪退。
    """
    temp_path = _prepare_output(output_path)

    # FIX-07/NEW-13: 初始化 COM 线程模型（STA，Word COM 要求）
    # M-04 修复：移除静默降级，缺少依赖时直接抛出明确错误
    try:
        import pythoncom
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
    except ImportError:
        raise RuntimeError(
            '缺少依赖：pythoncom 不可用\n'
            '请安装 pywin32：pip install pywin32'
        )

    try:
        import pywintypes
        _com_error_cls = getattr(pywintypes, 'com_error', Exception)
    except ImportError:
        raise RuntimeError(
            '缺少依赖：pywintypes 不可用\n请确认已安装 pywin32。'
        )

    try:
        # docx2pdf 内部使用 pywin32 调用 Word COM 对象
        from docx2pdf import convert as docx2pdf_convert

        # 写入临时文件，成功后再重命名
        docx2pdf_convert(input_path, temp_path)

        # 确保文件已生成
        if not os.path.isfile(temp_path):
            raise RuntimeError('docx2pdf 未生成输出文件')

        # 重命名 temp → 最终文件
        finalize_file(temp_path, output_path)

    except _com_error_cls as e:
        error_msg = _parse_com_error(e)
        raise RuntimeError(
            f'Word 转换失败：{error_msg}\n'
            '请确认已安装 Microsoft Word。'
        )
    except ImportError as e:
        raise RuntimeError(
            f'缺少依赖：{e}\n请确认已安装 pywin32。'
        )
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f'DOCX 转换失败：{e}')
    finally:
        # FIX-07: 释放 COM
        try:
            import pythoncom
            pythoncom.CoUninitialize()
        except (ImportError, Exception):
            pass


def _parse_com_error(e) -> str:
    """解析 pywintypes.com_error 为可读消息。"""
    try:
        if hasattr(e, 'strerror') and e.strerror:
            return str(e.strerror)
        if hasattr(e, 'args') and e.args:
            return str(e.args[1]) if len(e.args) > 1 else str(e.args[0])
    except Exception:
        pass
    return 'Microsoft Word COM 组件错误，请检查 Word 安装'

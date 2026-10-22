"""真实 API/Milvus/嵌入链路验收，临时资料会在 finally 中清理。

容器内运行：python smoke_live_rag.py
指定地址：python smoke_live_rag.py --base-url http://127.0.0.1:8000
只复用 seed.py 中的陈老师，不创建测试用户或聊天会话。
"""
from __future__ import annotations

import argparse
from urllib.parse import urlsplit
from uuid import uuid4

import requests


class SmokeFailure(RuntimeError):
    """仅包含可安全打印的检查摘要，禁止附带远程响应。"""


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def _json(response: requests.Response, expected_status: int, step: str) -> dict:
    _check(response.status_code == expected_status, f"{step}：HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError:
        raise SmokeFailure(f"{step}：返回了无效 JSON") from None
    _check(isinstance(payload, dict), f"{step}：响应结构无效")
    return payload


def run(base_url: str) -> int:
    marker = uuid4().hex
    title = f"RAG 上线验收韦达定理 {marker}"
    source_name = f"Milvus 链路验收 {marker}"
    query = f"根据韦达定理，一元二次方程两个根的和与积分别是多少？验收标记 {marker}"
    content = (
        "韦达定理：对一元二次方程 ax² + bx + c = 0（a ≠ 0），"
        "若两个根为 x1、x2，则两根之和 x1 + x2 = -b/a，两根之积 x1 × x2 = c/a。"
        f"本段为部署后临时验收资料，唯一验收标记 {marker}，测试结束后自动删除。"
    )
    document_ids: set[int] = set()
    create_attempted = False
    failed = False
    client = requests.Session()

    def request(method: str, path: str, **kwargs):
        return client.request(method, base_url + path, timeout=(5, 90), **kwargs)

    def search():
        return _json(request("POST", "/api/teacher/knowledge/math/search",
                             json={"query": query, "limit": 8}), 200, "数学检索")

    try:
        login = _json(request("POST", "/api/auth/login", json={
            "username": "陈老师", "role": "teacher", "subject": "math",
        }), 200, "复用种子教师登录")
        user = login.get("user") or {}
        _check(user.get("name") == "陈老师" and user.get("role") == "teacher", "种子教师身份不符")
        token = login.get("token")
        _check(isinstance(token, str) and bool(token), "登录未返回有效凭证")
        client.headers["Authorization"] = f"Bearer {token}"
        print("[通过] 已复用种子教师的数学登录")

        # 不另行登录其他学科：登录会增加 TeacherSubject，改变权限本身。
        forbidden = None
        for subject in ("english", "physics", "chemistry", "biology", "history", "geography", "politics", "chinese"):
            response = request("GET", f"/api/teacher/knowledge/{subject}")
            if response.status_code == 403:
                forbidden = subject
                break
            _check(response.status_code == 200, f"跨学科权限检查：HTTP {response.status_code}")
        _check(forbidden is not None, "当前教师拥有所有学科权限，无法验证未授权学科的 403")
        response = request("POST", f"/api/teacher/knowledge/{forbidden}/search", json={"query": query})
        _check(response.status_code == 403, f"未授权学科检索未返回 403（HTTP {response.status_code}）")
        print("[通过] 未授权学科的知识库读取和检索均返回 403")

        create_attempted = True
        saved = _json(request("POST", "/api/teacher/knowledge/math", json={
            "title": title, "content": content, "source_name": source_name,
        }), 200, "临时资料入库")
        document_id = saved.get("id")
        _check(isinstance(document_id, int) and not isinstance(document_id, bool), "资料入库未返回有效 ID")
        document_ids.add(document_id)
        _check(saved.get("passage_count", 0) > 0, "资料未生成检索片段")
        _check(saved.get("vector_status") == "ready", "Milvus 向量入库尚未就绪")
        print("[通过] 临时资料已保存片段并完成真实向量入库")

        found = search()
        _check(found.get("retrieval_mode") == "hybrid", "真实检索未使用 hybrid 模式")
        _check(found.get("rerank_mode") == "model", "真实检索未使用百炼模型重排")
        items = found.get("items")
        _check(isinstance(items, list), "检索结果结构无效")
        matches = [item for item in items if item.get("document_id") == document_id]
        _check(bool(matches), "混合检索未命中临时资料")
        hit = matches[0]
        _check(hit.get("source_name") == source_name, "命中资料缺少正确来源")
        _check(str(hit.get("citation", "")).startswith(f"[资料{document_id}-片段"), "命中资料缺少可追溯引用")
        _check(marker in hit.get("content", "") and "韦达定理" in hit.get("content", ""), "命中内容与临时资料不符")
        print("[通过] 真实 hybrid 检索及百炼模型重排命中资料，正文、来源与引用一致")
    except SmokeFailure as exc:
        failed = True
        print(f"[失败] {exc}")
    except Exception as exc:
        failed = True
        # 不打印 requests 错误正文、URL、响应或认证头。
        print(f"[失败] 真实链路检查发生 {type(exc).__name__}")
    finally:
        if create_attempted:
            try:
                # 创建请求即使在收到响应前超时，也可能已经提交；用唯一标题兜底找回。
                try:
                    listing = _json(request("GET", "/api/teacher/knowledge/math"), 200, "清理前读取临时资料")
                    listed = listing.get("items")
                    _check(isinstance(listed, list), "清理前资料列表结构无效")
                    document_ids.update(item["id"] for item in listed if item.get("title") == title)
                except Exception:
                    if not document_ids:
                        raise SmokeFailure("无法定位创建请求可能保存的临时资料") from None
                    # 已知 ID 仍然必须清理，不能被列表的临时故障阻断。
                for document_id in sorted(document_ids):
                    deleted = request("DELETE", f"/api/teacher/knowledge/math/{document_id}")
                    if deleted.status_code == 404:
                        continue
                    result = _json(deleted, 200, "删除临时资料")
                    _check(result.get("deleted") is True, "临时资料删除未确认")
                    _check(not result.get("warnings"), "本地资料已删除，但远程向量清理仍有警告")
                remaining = search().get("items")
                _check(isinstance(remaining, list), "清理后检索结果结构无效")
                _check(not any(item.get("document_id") in document_ids or marker in item.get("content", "")
                               for item in remaining), "临时资料删除后仍可被检索")
                print("[通过] 临时资料及向量已清理，后续检索不再返回该资料")
            except SmokeFailure as exc:
                failed = True
                print(f"[失败] 清理检查：{exc}")
            except Exception as exc:
                failed = True
                print(f"[失败] 临时资料清理发生 {type(exc).__name__}，请检查验收资料是否残留")
        client.close()
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="验收真实 Remedi API、Milvus 与向量模型链路，并清理临时资料。")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error("--base-url 必须是无凭证、查询参数或片段的 HTTP(S) 地址")
    return run(args.base_url.rstrip("/"))


if __name__ == "__main__":
    raise SystemExit(main())

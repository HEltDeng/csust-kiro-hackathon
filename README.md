# K 校园计划 · K Campus Idea

同一个项目同时包含活动官网、报名服务和管理后台。服务沿用已有报名数据库；旧的“我的长理”官网代码不在本项目内，也不会被覆盖。

- `dist/`：活动官网与报名页。
- `dist/admin/`：管理后台。
- `server/`：Python 标准库服务、管理接口和生产服务配置。
- `tests/`：报名、管理、公告和邮件转发验证。
- `ops/deploy-campus.py`：现有服务器上的部署与回滚脚本。

网站图标使用 Kiro 官网图标；`kiro-ghost.svg` 为移除底色的页面装饰版本。

## 线上使用

- 官网：<https://mychangliapp.cn/>（跳转到活动网站；旧官网首页文件保留原样）
- 活动页面：<https://mychangliapp.cn/events/kiro-2026/>
- 报名页面：<https://mychangliapp.cn/events/kiro-2026/register.html>
- 管理后台：<https://mychangliapp.cn/events/kiro-2026/admin/>

后台可查看、搜索、导出报名，发布和撤下活动公告，并在企业邮箱配置完成后将单条报名信息发送到指定邮箱。公告以纯文本显示，发布后自动出现在活动首页。登录信息保存在项目的 `管理工具/` 中，不纳入代码仓库；登录后可在“账户安全”中修改密码。

邮箱需要服务商的 SMTP 地址、邮箱账号及授权码，支持 SSL 465 或 STARTTLS 587。邮箱服务商尚未确定，未配置前转发不可用。密码仅保存在服务器服务专用目录（权限 0600），不会返回给后台页面；保存时留空会保留现有授权码。配置完成后需由管理员实际发送一封邮件确认服务商连接。

后台登录采用加盐密码派生、短期会话、同源检查、CSRF 校验及登录限速；报名数据和邮箱授权码不会进入 Git 或应用请求日志。定期备份和密码管理仍需由管理员维护。

## 本地开发

```sh
KIRO_PREVIEW=1 KIRO_REGISTRATION_OPEN=1 KIRO_PORT=8826 \
KIRO_DATABASE=/tmp/kiro-preview.sqlite3 \
KIRO_ALLOWED_ORIGINS=http://127.0.0.1:8826 python3 server/server.py
python3 -m unittest discover -s tests -v
```

本地预览需要先生成测试用 `admin-bootstrap.json`，格式和密码派生方式见 `server/management.py`。不要把真实报名信息、管理员密码或企业邮箱授权码放入源码目录或仓库。

## 生产部署

生产由 Nginx 与 `kiro-hackathon.service` 运行。`ops/deploy-campus.py` 对比部署前文件摘要，在服务器创建受限备份，升级服务和活动静态页，检查 Nginx 配置后切换首页；异常时恢复配置、代码和服务。数据库始终沿用原实例，不用备份覆盖线上报名数据。

仅切换 `/` 和 `/index.html` 到活动页面；原官网代码、APP 的配置、下载、隐私和其他路径保持原样。旧版 `ops/` 部署脚本留作历史参考，不应再用于更新包含后台的版本。

## Git 仓库

- 完整项目：<https://github.com/HEltDeng/csust-kiro-hackathon>，包含网站、后台、测试和运维脚本。
- 前端源码：<https://github.com/HEltDeng/csust-kiro-hackathon-frontend>，对应完整项目的 `dist/` 目录。
- 后端源码：<https://github.com/HEltDeng/csust-kiro-hackathon-backend>，对应完整项目的 `server/` 目录。

完整项目是主要开发位置；前端和后端仓库是对应目录的 Git 子树。测试及部署脚本保留在完整项目中。提交完整项目后，可从完整项目的根目录同步拆分仓库；新克隆的完整项目需先添加远程地址：

```sh
git remote add frontend https://github.com/HEltDeng/csust-kiro-hackathon-frontend.git
git remote add backend https://github.com/HEltDeng/csust-kiro-hackathon-backend.git
git subtree push --prefix=dist frontend main
git subtree push --prefix=server backend main
```

# Vidferry 项目管家机器人

## 目的

飞书机器人是现有只读 Vidferry Agent 的远程入口，也是面向非开发者的项目管家。它可以解释项目状态和引导查询，不会主动发送提醒。它不会从飞书执行下载、处理、发布、登录、配置修改、数据库写入或删除。

## 使用方式

可直接发送：

- `现在有什么要处理`
- `为什么失败`
- `账号是否正常`
- `下一步怎么做`
- 某个视频到哪一步了

前四类问题由项目管家直接查询；其他问题继续由已有 Agent 和只读工具回答。结果卡片提供“查看异常”“待确认”“项目概览”“账号状态”按钮，以及部署时配置的 Web 控制台链接。所有按钮均为查询或跳转，不执行写操作。

## 配置与部署

真实凭据仅保存在 `.env`：

```env
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_ALLOWED_OPEN_IDS=ou_xxx
FEISHU_BUTLER_CONSOLE_URL=https://your-console.example.com
```

运行 `python run_feishu_robot.py` 单独启动机器人；`python run.py` 不会启动飞书长连接。一个飞书应用同一时刻只应运行一个机器人进程。共享一个获授权飞书账号是允许的，但日志和 Agent 会话只能追溯到该账号，不能区分实际使用者。

`FEISHU_BUTLER_CONSOLE_URL` 必须是手机能访问的部署地址，生产环境建议 HTTPS；默认的 `127.0.0.1` 仅适用于本机浏览器。

飞书开发者后台除现有 `im.message.receive_v1` 事件订阅外，还需要在“回调配置”中选择长连接并订阅新版 `card.action.trigger`，卡片按钮才可用。不要同时保留旧版卡片回调配置，以免重复处理。

## 验收与排障

1. 启动后确认 `logs/feishu_robot.log` 出现飞书机器人启动记录。
2. 手机发送一条项目管家查询并点击卡片按钮，确认无原始 JSON。
3. 确认日志和飞书消息中没有 App Secret、API Key、Cookie 或完整本机路径。
4. 图片结果可发送；MP4 等视频文件不得发送。

机器人无回复时，依次检查 `.env` 中凭据和允许账号是否存在、飞书应用是否已发布且订阅 `im.message.receive_v1` 长连接、以及当前部署机器是否唯一运行机器人进程。

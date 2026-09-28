# Kiến trúc chi tiết OpenGuard Kids

Đây là kiến trúc mục tiêu theo mục 4 của đề bài. Một khối xuất hiện trong sơ đồ
không có nghĩa là khối đó đã được hiện thực ở tuần 1.

## Kiến trúc trên máy trẻ

```mermaid
%%{init: {"themeVariables": {"fontSize": "18px"}, "flowchart": {"nodeSpacing": 35, "rankSpacing": 45}}}%%
flowchart TB
    subgraph userSession ["PHIÊN NGƯỜI DÙNG CỦA TRẺ"]
        direction LR
        remainingTime["Đồng hồ còn lại"]
        blockReason["Lý do bị chặn"]
        childRequest["Xin thêm giờ - Báo chặn nhầm"]
        transparency["Màn hình minh bạch"]
        trayUi["Tray UI"]

        trayUi --- remainingTime
        trayUi --- blockReason
        trayUi --- childRequest
        trayUi --- transparency
    end

    subgraph systemSession ["WINDOWS SERVICE - LOCALSYSTEM"]
        direction LR
        agentCore["Agent Core"]
        policyEnforcer["Policy Enforcer"]
        screenCounter["Screen-time Counter"]
        appController["App Controller"]
        dnsProxy["DNS Proxy 127.0.0.1:53"]
        eventSync["Heartbeat và Event Sync"]

        agentCore --- policyEnforcer
        agentCore --- screenCounter
        agentCore --- appController
        agentCore --- dnsProxy
        agentCore --- eventSync
    end

    localStore[("SQLite trong ProgramData: policy cache và event queue")]
    remoteServer["OGK Server"]

    trayUi <-->|"Named pipe hoặc HTTP localhost có token"| agentCore
    agentCore <-->|"ACL chỉ SYSTEM và Administrators"| localStore
    eventSync <-->|"HTTPS và WebSocket"| remoteServer
```

## Kiến trúc Server và Dashboard

```mermaid
%%{init: {"themeVariables": {"fontSize": "18px"}, "flowchart": {"nodeSpacing": 35, "rankSpacing": 45}}}%%
flowchart TB
    subgraph parentDashboard ["DASHBOARD PHỤ HUYNH - WEB MOBILE FRIENDLY"]
        direction LR
        loginUi["Đăng nhập"]
        childUi["Quản lý trẻ và thiết bị"]
        policyUi["Quota - Lịch tuần - Danh sách chặn"]
        requestUi["Duyệt yêu cầu của trẻ"]
        reportUi["Báo cáo và Audit Log"]
    end

    subgraph fastApiServer ["OGK SERVER - FASTAPI VÀ UVICORN"]
        direction LR
        authApi["/auth"]
        enrollApi["/enroll"]
        policyApi["/policy"]
        eventApi["/events"]
        commandApi["/commands"]
        reportApi["/reports"]
        auditApi["/audit"]
    end

    serverStore[("SQLite WAL qua SQLAlchemy: parent, child, device, token, policy, event, command, audit")]
    windowsAgent["Windows Agent"]

    loginUi -->|"HTTPS"| authApi
    childUi -->|"HTTPS"| enrollApi
    policyUi -->|"HTTPS"| policyApi
    requestUi -->|"HTTPS"| commandApi
    reportUi -->|"HTTPS"| reportApi
    reportUi -->|"HTTPS"| auditApi

    authApi --> serverStore
    enrollApi --> serverStore
    policyApi --> serverStore
    eventApi --> serverStore
    commandApi --> serverStore
    reportApi --> serverStore
    auditApi --> serverStore

    windowsAgent <-->|"Heartbeat, policy và events"| eventApi
    windowsAgent <-->|"Lệnh khẩn qua WebSocket"| commandApi
```

## Đối chiếu với đề bài

| Nội dung bắt buộc ở mục 4 | Vị trí trong sơ đồ |
|---|---|
| Windows Service chạy LocalSystem | Khối `WINDOWS SERVICE - LOCALSYSTEM` |
| Policy Enforcer | Khối `Policy Enforcer` |
| Screen-time Counter | Khối `Screen-time Counter` |
| App Controller | Khối `App Controller` |
| DNS Proxy tại 127.0.0.1:53 | Khối `DNS Proxy 127.0.0.1:53` |
| Tray UI chạy trong phiên người dùng | Khối `PHIÊN NGƯỜI DÙNG CỦA TRẺ` |
| Local SQLite và hàng đợi ngoại tuyến | Khối `SQLite trong ProgramData` |
| FastAPI, Uvicorn và các nhóm API | Khối `OGK SERVER` |
| SQLite WAL và SQLAlchemy | Kho dữ liệu Server |
| Dashboard dùng được trên điện thoại | Khối `DASHBOARD PHỤ HUYNH` |
| HTTPS, heartbeat và WebSocket | Các đường nối Agent–Server |

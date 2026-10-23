# T27 界面检查

范围为 N01/D08、登录后的正式首页及独立原生品牌模块。沿用项目 Desktop v6 design-tokens.json、boss-v6.css、登录Logo、大鹏静态素材及待机动画。动画源24帧、720×408、无限循环；产品地址使用boss-idle.webp，内容与原始动画一致。动画层随机选择连续曲线路径，保持素材比例并且不接收指针操作。新增桌面图标使用imagegen内置工具制作，1254×1254 PNG master导出16—1024像素ICNS；登录Logo与吉祥物保持原有资源。

严格TypeScript及Vite生产构建通过。独立真实nanobot登录服务执行DOM、表单、身份、刷新、退出和自然过期检查，证据引用 `../../evidence/T27/login-dom.json`。布局检查包含1440×1024、1280×800、1024×768和CSS200%缩放，根容器四边误差不超过1 CSS px，没有整页横向滚动。系统减少动态效果变更会切换真实动画和静态资源。

独立Electron宿主名称、标题、高清图标加载及实际像素尺寸通过，证据 `../../evidence/T27/native-brand.json`。登录后的F01通过正式业务API读取本目录独立SQLite，维持SIMULATED资料标识。公共产品构建、完整Runtime、Electron200%原生缩放和安装包仍需W3接入后验证。页面视觉检查NOT_RUN；仅按用户授权生成并检查新桌面图标。

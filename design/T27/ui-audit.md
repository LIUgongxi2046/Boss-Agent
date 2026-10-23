# T27 界面检查

范围为 N01/D08 与独立原生品牌模块。沿用项目 Desktop v6 design-tokens.json、boss-v6.css、项目Logo、大鹏静态素材及待机动画。动画源24帧、720×408、无限循环；产品地址使用boss-idle.webp，内容与原始动画一致。ICNS由同一Logo转换，开发PNG与原始资源字节一致。没有新增生成图片。

严格TypeScript及Vite生产构建通过。独立真实nanobot登录服务执行DOM、表单、身份、刷新、退出和自然过期检查，证据引用 `../../evidence/T27/login-dom.json`。布局检查包含1440×1024、1280×800、1024×768和CSS200%缩放，根容器四边误差不超过1 CSS px，没有整页横向滚动。系统减少动态效果变更会切换真实动画和静态资源。

独立Electron宿主名称、标题、项目图标加载通过，证据 `../../evidence/T27/native-brand.json`。公共产品构建、完整工作区、Electron200%原生缩放和安装包仍需W3接入后验证。视觉检查NOT_RUN。

# 高清品牌资产提示词

工具为imagegen内置工具，两个生成任务分别提供原始参考图片。

桌面图标引用`../../Boss-Agent-Desktop-Complete-v6/assets/boss-logo-from-reference.png`：严格保留参考Logo的蓝绿交织轮廓、右侧蓝色圆点、绿色下部形状、颜色关系和比例，制作边缘清晰的高清透明PNG。保持首页与登录页使用的同款标志，不添加文字、水印或场景。

图标master为`../../validation/desktop/branding/boss-agent-hd.png`，1332×1181；运行PNG为同目录`boss-agent.png`。`prepare.cjs`保留比例并生成16—1024像素ICNS。登录与首页品牌继续使用原始Logo。

扑翼图集引用`../../Boss-Agent-Desktop-Complete-v6/assets/dapeng-front.png`：严格保持参考大鹏的蓝绿白配色、身体比例、面部、羽翼和材质，制作四列两行、八个等大单元的连续扑翼图集。羽翼从上举、展开、下压连续变化并回到上举，角色居中，四周保持透明，不添加文字、水印或场景。

图集保存为`assets/boss-flight-sprite.png`，1774×887。运行时按四列两行显示八帧，0.96秒完成一次扑翼；随机曲线、远近缩放与转弯姿态由界面动画控制。

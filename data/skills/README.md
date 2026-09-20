# data/skills · 技能包（Skills）

**用途**：一个技能 = 一个目录，目录内 `SKILL.md` 是**注入模型的指令正文**（渐进式加载，只在调用时注入，省 token）。

```
data/skills/
├─ jd-breakdown/SKILL.md      JD 拆解
├─ resume-tailor/SKILL.md     简历定向润色
├─ interview-drill/SKILL.md   面试出题与追问
└─ intel-brief/SKILL.md       情报摘要与风险标记
```

**SKILL.md 格式**

```markdown
---
title: 显示名称
description: 一句话说明用途
---
（正文：给模型的指令。写清目标、步骤、输出格式与禁止事项。）
```

**约定**
- 目录名用英文小写连字符（`<name>`），界面用它做标识；显示名走 front-matter 的 `title`。
- 目录内可再加脚本、模板、示例文件，作为该技能的配套资源。
- 支持界面新建/编辑/删除，以及从公开 URL 导入 SKILL.md（如 GitHub raw）。
- 首次运行会自动生成上面 4 个内置技能。
- 玩法详见 `docs/模块/06-扩展中心.md`。

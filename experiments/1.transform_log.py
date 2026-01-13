import re
import os

# 文件路径
input_file = "/root/shared-nvme/work/agent/OpenRCA/Market_cloudbed-1_deepseek-r1-250528.log"
output_file = os.path.splitext(input_file)[0] + "_clean.md"

# 匹配 ANSI 转义序列：\x1b[...m，包括 \x1b 和 [ 开头
# 支持 \x1b 或 \033 或 \u001b（三种写法都可能）
ansi_pattern = re.compile(r'\x1b\[[0-9;]*m|\033\[[0-9;]*m|\\u001b\[[0-9;]*m')

# 读取文件
with open(input_file, 'r', encoding='utf-8') as f:
    content = f.read()

# 清除所有 ANSI 序列
cleaned_content = ansi_pattern.sub('', content)

# 写入新文件
with open(output_file, 'w', encoding='utf-8') as f:
    f.write(cleaned_content)

print(f"✅ 已成功清理 ANSI 颜色码！")
print(f"输出文件：{output_file}")
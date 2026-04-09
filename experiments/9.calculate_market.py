# 定义输入字符串
str1 = "0.029412,0.279412,0.308824"
str2 = "0.103896,0.142857,0.246753"

# 1. 将字符串分割并转换为浮点数列表
nums1 = list(map(float, str1.split(',')))
nums2 = list(map(float, str2.split(',')))

# 2. 计算加权结果
# 公式：(str1 * 68 + str2 * 78) / 146
# 使用 zip 配对，列表推导式计算
result_nums = []
for n1, n2 in zip(nums1, nums2):
    weighted_val = (n1 * 68 + n2 * 78) / 146
    result_nums.append(weighted_val)

# 3. 格式化输出
# 将结果转换回字符串形式
# 这里直接转换，保留了计算出的精度
result_str = ",".join(str(x) for x in result_nums)

print(result_str)
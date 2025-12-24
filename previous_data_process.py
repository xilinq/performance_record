# previous_data_process.py
import csv
from datetime import datetime
from collections import OrderedDict

def convert_period_format(period_str):
    """
    将时期格式从 "2024.01上" 转换为 "2024-01-First Half"
    将时期格式从 "2024.01下" 转换为 "2024-01-Second Half"
    """
    if not period_str:
        return ""
    
    # 替换点号为短横线
    period_str = period_str.replace('.', '-')
    
    # 处理上下半月
    if period_str.endswith('上'):
        return period_str[:-1] + '-First Half'
    elif period_str.endswith('下'):
        return period_str[:-1] + '-Second Half'
    
    return period_str

def process_previous_data():
    """
    读取previous_data.csv并转换为performance_backup.csv格式
    """
    input_file = 'previous_data.csv'
    output_file = 'converted_performance_data.csv'
    
    # 用于存储转换后的数据
    performance_data = []
    summary_data = {}
    
    # 记录处理顺序，确保输出顺序与输入一致
    processed_records = OrderedDict()
    
    # 记录每个时期的编号顺序
    period_counters = OrderedDict()
    period_order = OrderedDict()  # 记录每个时期内人员的出现顺序
    
    try:
        with open(input_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                # 跳过空行或无效行
                if not row.get('姓名') or not row.get('时期'):
                    continue
                
                name = row['姓名'].strip()
                period_raw = row['时期'].strip()
                area = row['左区'].strip() if row.get('左区') else ''
                pv = row['pv'].strip() if row.get('pv') else '0'
                orders = row['单量'].strip() if row.get('单量') else '0'
                
                # 跳过无效数据
                if not name or not period_raw:
                    continue
                
                # 转换时期格式
                period = convert_period_format(period_raw)
                
                # 创建唯一标识符
                record_key = f"{name}_{period}"
                
                # 如果这个人员和时期组合还没有记录，创建新记录
                if record_key not in processed_records:
                    # 为该时期分配编号
                    if period not in period_counters:
                        period_counters[period] = 0
                        period_order[period] = []
                    
                    period_counters[period] += 1
                    period_order[period].append(record_key)
                    
                    processed_records[record_key] = {
                        'name': name,
                        'period': period,
                        'sort_order': period_counters[period],  # 该时期内的编号
                        'left_perf': 0.0,
                        'right_perf': 0.0,
                        'left_orders': 0,
                        'right_orders': 0,
                        'left_growth_pct': 0.0,
                        'right_growth_pct': 0.0,
                        'total_growth_pct': 0.0
                    }
                
                # 根据区域分配数据
                try:
                    pv_value = float(pv) if pv else 0.0
                    orders_value = int(orders) if orders else 0
                except (ValueError, TypeError):
                    pv_value = 0.0
                    orders_value = 0
                
                if area == '左区':
                    processed_records[record_key]['left_perf'] = pv_value
                    processed_records[record_key]['left_orders'] = orders_value
                elif area == '右区':
                    processed_records[record_key]['right_perf'] = pv_value
                    processed_records[record_key]['right_orders'] = orders_value
        
        # 将处理好的数据转换为列表，按照原始输入的顺序
        # 先按时期分组，再按每个时期内的顺序排列
        grouped_by_period = OrderedDict()
        for record_key, record in processed_records.items():
            period = record['period']
            if period not in grouped_by_period:
                grouped_by_period[period] = []
            grouped_by_period[period].append(record)
        
        # 按时期内的编号排序，然后合并所有时期的数据
        for period in grouped_by_period:
            # 按编号排序该时期的记录
            sorted_records = sorted(grouped_by_period[period], key=lambda x: x['sort_order'])
            for record in sorted_records:
                performance_data.append([
                    record['name'],
                    record['period'],
                    record['left_perf'],
                    record['right_perf'],
                    record['left_orders'],
                    record['right_orders'],
                    record['left_growth_pct'],
                    record['right_growth_pct'],
                    record['total_growth_pct']
                ])
        
        # 写入输出文件
        with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            
            # 写入文件头信息（与performance_backup.csv格式一致，但添加编号字段）
            writer.writerow(['# 业绩数据备份文件'])
            writer.writerow(['# 导出时间:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
            writer.writerow(['# 数据格式: 编号,姓名,时期,左区业绩,右区业绩,左区订单,右区订单,左区增长%,右区增长%,总增长%'])
            writer.writerow([])
            
            # 写入业绩数据段
            writer.writerow(['[PERFORMANCE_DATA]'])
            writer.writerow(['编号', '姓名', '时期', '左区业绩', '右区业绩', '左区订单', '右区订单', 
                           '左区增长%', '右区增长%', '总增长%'])
            
            # 写入转换后的数据，添加编号
            current_period = None
            period_number = 0
            
            for row in performance_data:
                period = row[1]  # 时期在第1个位置
                
                # 如果是新的时期，重置编号
                if period != current_period:
                    current_period = period
                    period_number = 0
                
                period_number += 1
                
                # 插入编号作为第一列
                row_with_number = [period_number] + row
                writer.writerow(row_with_number)
            
            writer.writerow([])
            
            # 写入总结数据段（空的，因为原始数据中没有总结信息）
            writer.writerow(['[SUMMARY_DATA]'])
            writer.writerow(['时期', '总结内容'])
            
            # 如果有总结数据，在这里写入
            for period, summary in summary_data.items():
                writer.writerow([period, summary])
        
        print(f"转换完成！")
        print(f"输入文件: {input_file}")
        print(f"输出文件: {output_file}")
        print(f"共转换了 {len(performance_data)} 条记录")
        
        # 显示一些统计信息
        unique_names = set(record[0] for record in performance_data)
        unique_periods = set(record[1] for record in performance_data)
        
        print(f"包含 {len(unique_names)} 个不同的人员")
        print(f"包含 {len(unique_periods)} 个不同的时期")
        print(f"人员列表: {', '.join(sorted(unique_names))}")
        print("\n时期列表和每个时期的人员数量:")
        for period in sorted(unique_periods):
            count = len([r for r in performance_data if r[1] == period])
            print(f"  - {period}: {count} 人")
            
    except FileNotFoundError:
        print(f"错误: 找不到文件 {input_file}")
        print("请确保 previous_data.csv 文件存在于当前目录中")
    except Exception as e:
        print(f"处理过程中出现错误: {e}")

def preview_conversion_with_numbering():
    """
    预览转换结果的前几行，包括编号信息
    """
    input_file = 'previous_data.csv'
    
    try:
        with open(input_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            print("原始数据预览（含编号预览）:")
            print("-" * 80)
            
            # 临时处理逻辑，用于预览编号
            processed_records = OrderedDict()
            period_counters = OrderedDict()
            
            count = 0
            for row in reader:
                if count >= 20:  # 显示前20行
                    break
                    
                if row.get('姓名') and row.get('时期'):
                    name = row['姓名'].strip()
                    period_raw = row['时期'].strip()
                    area = row.get('左区', '').strip()
                    pv = row.get('pv', '').strip()
                    orders = row.get('单量', '').strip()
                    
                    period_converted = convert_period_format(period_raw)
                    record_key = f"{name}_{period_converted}"
                    
                    # 为该时期分配编号
                    if record_key not in processed_records:
                        if period_converted not in period_counters:
                            period_counters[period_converted] = 0
                        
                        period_counters[period_converted] += 1
                        sort_order = period_counters[period_converted]
                        processed_records[record_key] = sort_order
                        
                        print(f"编号: {sort_order}, 姓名: {name}, 时期: {period_converted}")
                        print(f"  区域: {area}, PV: {pv}, 单量: {orders}")
                        count += 1
                        print()
                    
    except FileNotFoundError:
        print(f"错误: 找不到文件 {input_file}")
    except Exception as e:
        print(f"预览过程中出现错误: {e}")

def preview_conversion():
    """
    预览转换结果的前几行
    """
    preview_conversion_with_numbering()

if __name__ == "__main__":
    print("=== Previous Data 转换工具 ===")
    print("功能: 将 previous_data.csv 转换为 performance_backup.csv 格式")
    print("特色: 每个时期的人员都会按出现顺序从1开始编号")
    print()
    
    # 首先预览转换
    print("1. 预览转换（含编号）:")
    preview_conversion()
    
    print("\n" + "="*60 + "\n")
    
    # 执行转换
    print("2. 执行转换:")
    process_previous_data()
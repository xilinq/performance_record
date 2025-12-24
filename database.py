# database.py
import sqlite3
import os
from pathlib import Path

class DatabaseManager:
    """负责所有数据库操作"""
    def __init__(self, db_name="performance.db"):
        self.db_path = Path(db_name)
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        """创建数据库表（如果不存在）"""
        # 业绩数据表，使用复合主键(name, period)确保唯一性
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS performance (
                name TEXT NOT NULL,
                period TEXT NOT NULL,
                left_perf REAL DEFAULT 0,
                right_perf REAL DEFAULT 0,
                left_orders INTEGER DEFAULT 0,
                right_orders INTEGER DEFAULT 0,
                left_growth_pct REAL DEFAULT 0,
                right_growth_pct REAL DEFAULT 0,
                total_growth_pct REAL DEFAULT 0,
                position TEXT DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                PRIMARY KEY (name, period)
            )
        ''')
        # 时期总结表
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS summaries (
                period TEXT PRIMARY KEY,
                summary_text TEXT
            )
        ''')
        
        # 所有人员姓名表
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS all_names (
                name TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        # 检查是否需要添加新列（兼容旧数据库）
        self.cursor.execute("PRAGMA table_info(performance)")
        columns = [row[1] for row in self.cursor.fetchall()]
        if 'left_growth_pct' not in columns:
            self.cursor.execute('ALTER TABLE performance ADD COLUMN left_growth_pct REAL DEFAULT 0')
        if 'right_growth_pct' not in columns:
            self.cursor.execute('ALTER TABLE performance ADD COLUMN right_growth_pct REAL DEFAULT 0')
        if 'total_growth_pct' not in columns:
            self.cursor.execute('ALTER TABLE performance ADD COLUMN total_growth_pct REAL DEFAULT 0')
        if 'position' not in columns:
            self.cursor.execute('ALTER TABLE performance ADD COLUMN position TEXT DEFAULT ""')
        if 'sort_order' not in columns:
            self.cursor.execute('ALTER TABLE performance ADD COLUMN sort_order INTEGER DEFAULT 0')
        
        self.conn.commit()
        
        # 初始化ALL_NAMES表
        self.initialize_all_names()

    def initialize_all_names(self):
        """初始化ALL_NAMES表，从现有的performance数据中提取所有姓名"""
        # 获取performance表中的所有不重复姓名
        self.cursor.execute("SELECT DISTINCT name FROM performance WHERE name IS NOT NULL AND name != ''")
        existing_names = [row[0] for row in self.cursor.fetchall()]
        
        # 将这些姓名添加到all_names表（如果不存在）
        for name in existing_names:
            self.add_name_to_all_names(name)
        
        print(f"初始化ALL_NAMES表完成，包含 {len(existing_names)} 个姓名")

    def add_name_to_all_names(self, name):
        """添加姓名到ALL_NAMES表"""
        if not name or not name.strip():
            return False
        
        name = name.strip()
        try:
            self.cursor.execute("""
                INSERT OR IGNORE INTO all_names (name, is_active) 
                VALUES (?, 1)
            """, (name,))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"添加姓名到ALL_NAMES失败: {e}")
            return False

    def get_all_names(self, active_only=True):
        """获取所有姓名列表，开头包含空白选项"""
        if active_only:
            self.cursor.execute("SELECT name FROM all_names WHERE is_active = 1 ORDER BY name")
        else:
            self.cursor.execute("SELECT name FROM all_names ORDER BY name")
        names = [row[0] for row in self.cursor.fetchall()]
        # 在列表开头添加空白选项
        return [""] + names

    def deactivate_name(self, name):
        """停用姓名（不删除，只标记为非活跃）"""
        self.cursor.execute("UPDATE all_names SET is_active = 0 WHERE name = ?", (name,))
        self.conn.commit()

    def activate_name(self, name):
        """激活姓名"""
        self.cursor.execute("UPDATE all_names SET is_active = 1 WHERE name = ?", (name,))
        self.conn.commit()

    def update_all_names_from_performance(self):
        """从performance表更新ALL_NAMES，确保performance中的姓名都在ALL_NAMES中"""
        self.cursor.execute("SELECT DISTINCT name FROM performance WHERE name IS NOT NULL AND name != ''")
        performance_names = [row[0] for row in self.cursor.fetchall()]
        
        new_names_count = 0
        for name in performance_names:
            # 检查是否已存在
            self.cursor.execute("SELECT COUNT(*) FROM all_names WHERE name = ?", (name,))
            if self.cursor.fetchone()[0] == 0:
                self.add_name_to_all_names(name)
                new_names_count += 1
        
        if new_names_count > 0:
            print(f"从performance表新增 {new_names_count} 个姓名到ALL_NAMES")
        
        return new_names_count

    def calculate_growth_percentage(self, name, period, left_perf, right_perf):
        """计算业绩增长百分比"""
        # 获取该人员的所有历史数据，按时期正序排序
        self.cursor.execute("""
            SELECT period, left_perf, right_perf 
            FROM performance 
            WHERE name = ? 
            ORDER BY period ASC
        """, (name,))
        
        history = self.cursor.fetchall()
        
        # 如果没有历史数据或当前是第一条记录，增长率为0
        if not history:
            return 0.0, 0.0, 0.0
        
        # 找到当前时期在历史记录中的位置
        current_index = -1
        for i, (hist_period, _, _) in enumerate(history):
            if hist_period == period:
                current_index = i
                break
        
        # 如果是第一条记录，增长率为0
        if current_index <= 0:
            return 0.0, 0.0, 0.0
        
        # 取前一期数据作为基准
        prev_period, prev_left, prev_right = history[current_index - 1]
        
        def calc_growth(current, previous):
            if previous == 0:
                return 100.0 if current > 0 else 0.0
            return ((current - previous) / previous) * 100.0
        
        left_growth = calc_growth(left_perf, prev_left)
        right_growth = calc_growth(right_perf, prev_right)
        total_growth = calc_growth(left_perf + right_perf, prev_left + prev_right)
        
        return left_growth, right_growth, total_growth

    def recalculate_all_growth_rates(self):
        """重新计算所有人员的增长率"""
        # 获取所有不重复的姓名
        self.cursor.execute("SELECT DISTINCT name FROM performance ORDER BY name")
        names = [row[0] for row in self.cursor.fetchall()]
        
        for name in names:
            # 获取该人员的所有记录，按时期正序排序
            self.cursor.execute("""
                SELECT period, left_perf, right_perf, left_orders, right_orders 
                FROM performance 
                WHERE name = ? 
                ORDER BY period ASC
            """, (name,))
            
            records = self.cursor.fetchall()
            
            for i, (period, left_perf, right_perf, left_orders, right_orders) in enumerate(records):
                if i == 0:
                    # 第一条记录，增长率为0
                    left_growth = right_growth = total_growth = 0.0
                else:
                    # 计算相对于前一期的增长率
                    prev_period, prev_left, prev_right, _, _ = records[i - 1]
                    
                    def calc_growth(current, previous):
                        if previous == 0:
                            return 100.0 if current > 0 else 0.0
                        return ((current - previous) / previous) * 100.0
                    
                    left_growth = calc_growth(left_perf, prev_left)
                    right_growth = calc_growth(right_perf, prev_right)
                    total_growth = calc_growth(left_perf + right_perf, prev_left + prev_right)
                
                # 更新增长率
                self.cursor.execute("""
                    UPDATE performance 
                    SET left_growth_pct = ?, right_growth_pct = ?, total_growth_pct = ? 
                    WHERE name = ? AND period = ?
                """, (left_growth, right_growth, total_growth, name, period))
        
        self.conn.commit()

    def recalculate_person_growth_rates(self, name):
        """重新计算特定人员的增长率"""
        # 获取该人员的所有记录，按时期正序排序
        self.cursor.execute("""
            SELECT period, left_perf, right_perf, left_orders, right_orders 
            FROM performance 
            WHERE name = ? 
            ORDER BY period ASC
        """, (name,))
        
        records = self.cursor.fetchall()
        
        for i, (period, left_perf, right_perf, left_orders, right_orders) in enumerate(records):
            if i == 0:
                # 第一条记录，增长率为0
                left_growth = right_growth = total_growth = 0.0
            else:
                # 计算相对于前一期的增长率
                prev_period, prev_left, prev_right, _, _ = records[i - 1]
                
                def calc_growth(current, previous):
                    if previous == 0:
                        return 100.0 if current > 0 else 0.0
                    return ((current - previous) / previous) * 100.0
                
                left_growth = calc_growth(left_perf, prev_left)
                right_growth = calc_growth(right_perf, prev_right)
                total_growth = calc_growth(left_perf + right_perf, prev_left + prev_right)
            
            # 更新增长率
            self.cursor.execute("""
                UPDATE performance 
                SET left_growth_pct = ?, right_growth_pct = ?, total_growth_pct = ? 
                WHERE name = ? AND period = ?
            """, (left_growth, right_growth, total_growth, name, period))
        
        self.conn.commit()

    def save_period_data(self, period, data_list):
        """保存一个时期的所有人员数据，使用INSERT OR REPLACE进行插入或更新"""
        # 如果是新格式，转换为旧格式保存
        original_period = period
        if "上" in period:
            original_period = period.replace("上", "First Half")
        elif "下" in period:
            original_period = period.replace("下", "Second Half")
        
        # 首先删除该时期的所有现有数据
        self.cursor.execute("DELETE FROM performance WHERE period = ?", (original_period,))
            
        for i, d in enumerate(data_list):
            # 确保姓名存在于ALL_NAMES中
            self.add_name_to_all_names(d['name'])
            
            query = '''
                INSERT INTO performance 
                (name, period, left_perf, right_perf, left_orders, right_orders, 
                 left_growth_pct, right_growth_pct, total_growth_pct, position, sort_order) 
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?)
            '''
            position = d.get('position', '')
            sort_order = d.get('sort_order', i)
            self.cursor.execute(query, (
                d['name'], original_period, d['left_perf'], d['right_perf'], 
                d['left_orders'], d['right_orders'], position, sort_order
            ))
        self.conn.commit()
        
        # 保存完成后，重新计算所有人员的增长率
        self.recalculate_all_growth_rates()
        
        # 自动备份到CSV
        self.export_to_csv("performance_backup.csv")
    
    def save_single_record(self, name, period, left_perf, right_perf, left_orders, right_orders, position='', sort_order=0):
        """保存或更新单个人员记录"""
        # 如果是新格式，转换为旧格式保存
        original_period = period
        if "上" in period:
            original_period = period.replace("上", "First Half")
        elif "下" in period:
            original_period = period.replace("下", "Second Half")
        
        # 确保姓名存在于ALL_NAMES中
        self.add_name_to_all_names(name)
            
        query = '''
            INSERT OR REPLACE INTO performance 
            (name, period, left_perf, right_perf, left_orders, right_orders,
             left_growth_pct, right_growth_pct, total_growth_pct, position, sort_order) 
            VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?)
        '''
        self.cursor.execute(query, (
            name, original_period, left_perf, right_perf, left_orders, right_orders, position, sort_order
        ))
        self.conn.commit()
        
        # 保存完成后，重新计算该人员的增长率
        self.recalculate_person_growth_rates(name)
        
        # 自动备份到CSV
        self.export_to_csv("performance_backup.csv")
    
    def delete_single_record(self, name, period):
        """删除单个人员记录"""
        # 如果是新格式，转换为旧格式删除
        original_period = period
        if "上" in period:
            original_period = period.replace("上", "First Half")
        elif "下" in period:
            original_period = period.replace("下", "Second Half")
            
        self.cursor.execute("DELETE FROM performance WHERE name = ? AND period = ?", (name, original_period))
        deleted_count = self.cursor.rowcount
        self.conn.commit()
        
        # 删除后，重新计算该人员的增长率
        if deleted_count > 0:
            self.recalculate_person_growth_rates(name)
            # 自动备份到CSV
            self.export_to_csv("performance_backup.csv")
        
        return deleted_count  # 返回被删除的行数
        
    def get_data_by_period(self, period):
        """获取特定时期的数据，按编号顺序排序"""
        # 如果是新格式，转换为旧格式查询
        original_period = period
        if "上" in period:
            original_period = period.replace("上", "First Half")
        elif "下" in period:
            original_period = period.replace("下", "Second Half")
            
        self.cursor.execute("""
            SELECT name, left_perf, right_perf, left_orders, right_orders, 
                   left_growth_pct, right_growth_pct, total_growth_pct, position, sort_order
            FROM performance WHERE period = ? 
            ORDER BY sort_order ASC, name ASC
        """, (original_period,))
        return self.cursor.fetchall()

    def get_all_data_by_name(self, name):
        """获取特定人员的所有时期完整数据，按时期从新到旧排序"""
        self.cursor.execute("""
            SELECT period, left_perf, right_perf, left_orders, right_orders,
                   left_growth_pct, right_growth_pct, total_growth_pct, position
            FROM performance 
            WHERE name = ? 
            ORDER BY period DESC
        """, (name,))
        data = self.cursor.fetchall()
        # 转换时期格式显示
        converted_data = []
        for row in data:
            period = self.convert_period_format(row[0])
            converted_row = (period,) + row[1:]
            converted_data.append(converted_row)
        return converted_data

    def get_data_by_name(self, name):
        """获取特定人员的所有时期数据，按时期排序（图表用）"""
        self.cursor.execute("SELECT period, left_perf, right_perf FROM performance WHERE name = ? ORDER BY period", (name,))
        return self.cursor.fetchall()

    def get_distinct_names(self):
        """获取所有不重复的姓名列表"""
        self.cursor.execute("SELECT DISTINCT name FROM performance ORDER BY name")
        return [row[0] for row in self.cursor.fetchall()]

    def convert_period_format(self, period):
        """将时期格式从旧格式转换为新格式"""
        if "First Half" in period:
            return period.replace("First Half", "上")
        elif "Second Half" in period:
            return period.replace("Second Half", "下")
        return period

    def get_distinct_periods(self):
        """获取所有不重复的时期列表，转换格式"""
        self.cursor.execute("SELECT DISTINCT period FROM performance ORDER BY period DESC")
        periods = [row[0] for row in self.cursor.fetchall()]
        # 转换时期格式
        converted_periods = [self.convert_period_format(period) for period in periods]
        return converted_periods

    def get_latest_performance_period(self):
        """获取PERFORMANCE_DATA表中的最新时期（不包括SUMMARY_DATA）"""
        self.cursor.execute("SELECT DISTINCT period FROM performance ORDER BY period DESC LIMIT 1")
        result = self.cursor.fetchone()
        return result[0] if result else None

    def save_summary(self, period, text):
        """保存或更新时期总结"""
        # 如果是新格式，转换为旧格式保存
        original_period = period
        if "上" in period:
            original_period = period.replace("上", "First Half")
        elif "下" in period:
            original_period = period.replace("下", "Second Half")
            
        self.cursor.execute("INSERT OR REPLACE INTO summaries (period, summary_text) VALUES (?, ?)", (original_period, text))
        self.conn.commit()
        
        # 自动备份到CSV
        self.export_to_csv("performance_backup.csv")

    def get_summary(self, period):
        """获取时期总结"""
        # 如果是新格式，转换为旧格式查询
        original_period = period
        if "上" in period:
            original_period = period.replace("上", "First Half")
        elif "下" in period:
            original_period = period.replace("下", "Second Half")
            
        self.cursor.execute("SELECT summary_text FROM summaries WHERE period = ?", (original_period,))
        result = self.cursor.fetchone()
        return result[0] if result else ""

    def export_to_csv(self, csv_file="performance_backup.csv"):
        """导出所有数据到CSV文件，包含编号"""
        import csv
        from datetime import datetime
        
        try:
            # 获取所有业绩数据，按时期和sort_order排序
            self.cursor.execute("""
                SELECT name, period, left_perf, right_perf, left_orders, right_orders,
                       left_growth_pct, right_growth_pct, total_growth_pct, sort_order
                FROM performance 
                ORDER BY period ASC, sort_order ASC, name ASC
            """)
            performance_data = self.cursor.fetchall()
            
            # 获取所有总结数据
            self.cursor.execute("SELECT period, summary_text FROM summaries ORDER BY period")
            summary_data = {period: summary for period, summary in self.cursor.fetchall()}
            
            with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                
                # 写入元数据
                writer.writerow(['# 业绩数据备份文件'])
                writer.writerow(['# 导出时间:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
                writer.writerow(['# 数据格式: 编号,姓名,时期,左区业绩,右区业绩,左区订单,右区订单,左区增长%,右区增长%,总增长%'])
                writer.writerow([])
                
                # 写入业绩数据头部
                writer.writerow(['[PERFORMANCE_DATA]'])
                writer.writerow(['编号', '姓名', '时期', '左区业绩', '右区业绩', '左区订单', '右区订单', 
                               '左区增长%', '右区增长%', '总增长%'])
                
                # 按时期分组，为每个时期重新编号
                current_period = None
                period_number = 0
                
                for row in performance_data:
                    name, period, left_perf, right_perf, left_orders, right_orders, left_growth_pct, right_growth_pct, total_growth_pct, sort_order = row
                    
                    # 如果是新的时期，重置编号
                    if period != current_period:
                        current_period = period
                        period_number = 0
                    
                    period_number += 1
                    
                    # 写入包含编号的数据行
                    writer.writerow([period_number, name, period, left_perf, right_perf, left_orders, right_orders, 
                                   left_growth_pct, right_growth_pct, total_growth_pct])
                
                writer.writerow([])
                
                # 写入总结数据头部
                writer.writerow(['[SUMMARY_DATA]'])
                writer.writerow(['时期', '总结内容'])
                
                # 写入总结数据
                for period, summary in summary_data.items():
                    # 处理总结中的换行符
                    clean_summary = summary.replace('\n', '\\n').replace('\r', '\\r') if summary else ''
                    writer.writerow([period, clean_summary])
            
            print(f"数据已导出到 {csv_file}")
            return True
            
        except Exception as e:
            print(f"导出CSV失败: {e}")
            return False

    def import_from_csv(self, csv_file="performance_backup.csv"):
        """从CSV文件导入数据"""
        import csv
        
        try:
            if not os.path.exists(csv_file):
                print(f"CSV文件不存在: {csv_file}")
                return False
            
            with open(csv_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                rows = list(reader)
            
            # 查找数据段
            performance_start = -1
            summary_start = -1
            
            for i, row in enumerate(rows):
                if row and row[0] == '[PERFORMANCE_DATA]':
                    performance_start = i + 2  # 跳过标题行
                elif row and row[0] == '[SUMMARY_DATA]':
                    summary_start = i + 2  # 跳过标题行
            
            if performance_start == -1:
                print("CSV文件格式错误：找不到业绩数据段")
                return False
            
            # 清空现有数据
            print("清空现有数据...")
            self.cursor.execute("DELETE FROM performance")
            self.cursor.execute("DELETE FROM summaries")
            
            # 导入业绩数据
            print("导入业绩数据...")
            performance_count = 0
            for i in range(performance_start, len(rows)):
                row = rows[i]
                if not row or row[0].startswith('[') or not row[0].strip():
                    break
                
                if len(row) >= 9:  # 检查是否有足够的列
                    try:
                        # 检测CSV格式：是否包含编号列
                        if len(row) >= 10 and row[0].isdigit():
                            # 新格式：编号,姓名,时期,左区业绩,右区业绩,左区订单,右区订单,左区增长%,右区增长%,总增长%
                            number = int(row[0])
                            name = row[1]
                            period = row[2]
                            left_perf = float(row[3])
                            right_perf = float(row[4])
                            left_orders = int(row[5])
                            right_orders = int(row[6])
                            left_growth_pct = float(row[7])
                            right_growth_pct = float(row[8])
                            total_growth_pct = float(row[9])
                            sort_order = number - 1  # 编号从1开始，sort_order从0开始
                        else:
                            # 旧格式：姓名,时期,左区业绩,右区业绩,左区订单,右区订单,左区增长%,右区增长%,总增长%
                            name = row[0]
                            period = row[1]
                            left_perf = float(row[2])
                            right_perf = float(row[3])
                            left_orders = int(row[4])
                            right_orders = int(row[5])
                            left_growth_pct = float(row[6])
                            right_growth_pct = float(row[7])
                            total_growth_pct = float(row[8])
                            sort_order = performance_count  # 使用行序号作为排序
                        
                        self.cursor.execute("""
                            INSERT INTO performance 
                            (name, period, left_perf, right_perf, left_orders, right_orders,
                             left_growth_pct, right_growth_pct, total_growth_pct, sort_order)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (name, period, left_perf, right_perf, left_orders, right_orders,
                             left_growth_pct, right_growth_pct, total_growth_pct, sort_order))
                        performance_count += 1
                    except (ValueError, IndexError) as e:
                        print(f"跳过无效的业绩数据行 {i+1}: {e}")
                elif len(row) >= 8:  # 兼容缺少总增长率的旧数据
                    try:
                        if row[0].isdigit():
                            # 新格式但缺少总增长率
                            number = int(row[0])
                            name = row[1]
                            period = row[2]
                            left_perf = float(row[3])
                            right_perf = float(row[4])
                            left_orders = int(row[5])
                            right_orders = int(row[6])
                            left_growth_pct = float(row[7]) if len(row) > 7 else 0.0
                            right_growth_pct = float(row[8]) if len(row) > 8 else 0.0
                            total_growth_pct = 0.0
                            sort_order = number - 1
                        else:
                            # 旧格式缺少增长率
                            name = row[0]
                            period = row[1]
                            left_perf = float(row[2])
                            right_perf = float(row[3])
                            left_orders = int(row[4])
                            right_orders = int(row[5])
                            left_growth_pct = float(row[6]) if len(row) > 6 else 0.0
                            right_growth_pct = float(row[7]) if len(row) > 7 else 0.0
                            total_growth_pct = 0.0
                            sort_order = performance_count
                        
                        self.cursor.execute("""
                            INSERT INTO performance 
                            (name, period, left_perf, right_perf, left_orders, right_orders,
                             left_growth_pct, right_growth_pct, total_growth_pct, sort_order)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (name, period, left_perf, right_perf, left_orders, right_orders,
                             left_growth_pct, right_growth_pct, total_growth_pct, sort_order))
                        performance_count += 1
                    except (ValueError, IndexError) as e:
                        print(f"跳过无效的业绩数据行 {i+1}: {e}")
            
            # 导入总结数据
            summary_count = 0
            if summary_start != -1:
                print("导入总结数据...")
                for i in range(summary_start, len(rows)):
                    row = rows[i]
                    if not row or not row[0].strip():
                        continue
                    
                    if len(row) >= 2:
                        try:
                            period = row[0]
                            summary = row[1].replace('\\n', '\n').replace('\\r', '\r') if row[1] else ''
                            
                            self.cursor.execute("""
                                INSERT INTO summaries (period, summary_text)
                                VALUES (?, ?)
                            """, (period, summary))
                            summary_count += 1
                        except Exception as e:
                            print(f"跳过无效的总结数据行 {i+1}: {e}")
            
            self.conn.commit()
            print(f"导入完成: {performance_count}条业绩记录, {summary_count}条总结记录")
            
            # 导入完成后更新ALL_NAMES
            self.update_all_names_from_performance()
            
            return True
            
        except Exception as e:
            print(f"导入CSV失败: {e}")
            self.conn.rollback()
            return False

    def auto_backup_to_csv(self):
        """自动备份到CSV文件"""
        from datetime import datetime
        backup_file = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return self.export_to_csv(backup_file)

    def __del__(self):
        """关闭数据库连接"""
        try:
            if hasattr(self, 'conn') and self.conn:
                self.conn.close()
        except:
            pass  # 忽略关闭连接时的任何错误


# ===================================================================
#  独立测试脚本
#  运行方式: python database.py
# ===================================================================
if __name__ == '__main__':
    import os
    print("--- Running DatabaseManager Test ---")
    
    # 1. 使用一个临时的测试数据库
    test_db_file = "test_performance.db"
    if os.path.exists(test_db_file):
        os.remove(test_db_file)
    
    db_test = DatabaseManager(test_db_file)
    print(f"1. Created test database: {test_db_file}")

    # 2. 准备测试数据
    period1_data = [
        {'name': '张三', 'left_perf': 100.5, 'right_perf': 150.0, 'left_orders': 10, 'right_orders': 12},
        {'name': '李四', 'left_perf': 200.0, 'right_perf': 50.5, 'left_orders': 15, 'right_orders': 5}
    ]
    period2_data = [
        {'name': '张三', 'left_perf': 120.0, 'right_perf': 180.0, 'left_orders': 11, 'right_orders': 15},
        {'name': '王五', 'left_perf': 300.0, 'right_perf': 350.0, 'left_orders': 20, 'right_orders': 22}
    ]
    period1 = "2023-01-First Half"
    period2 = "2023-01-Second Half"

    # 3. 测试数据插入
    db_test.save_period_data(period1, period1_data)
    db_test.save_period_data(period2, period2_data)
    print("2. Inserted data for two periods.")

    # 4. 测试按时期查询
    data = db_test.get_data_by_period(period1)
    assert len(data) == 2
    assert data[0][0] == '张三' # 姓名
    print(f"3. Fetched data for period '{period1}': {data}")

    # 5. 测试按姓名查询
    data_zhangsan = db_test.get_data_by_name('张三')
    assert len(data_zhangsan) == 2
    assert data_zhangsan[0][0] == period1 # 检查时期
    print(f"4. Fetched all data for '张三': {data_zhangsan}")
    
    # 6. 测试获取唯一列表
    names = db_test.get_distinct_names()
    periods = db_test.get_distinct_periods()
    assert '张三' in names and '李四' in names and '王五' in names
    assert period1 in periods and period2 in periods
    print(f"5. Distinct names: {names}, Distinct periods: {periods}")

    # 7. 测试总结功能
    summary_text = "这是第一个时期的总结。"
    db_test.save_summary(period1, summary_text)
    retrieved_summary = db_test.get_summary(period1)
    assert retrieved_summary == summary_text
    print(f"6. Saved and retrieved summary for '{period1}'.")

    # 8. 测试数据更新 (使用 save_single_record)
    db_test.save_single_record('张三', period1, 999.0, 999.0, 99, 99)
    updated_data = db_test.get_data_by_period(period1)
    # 现在应该有两条记录：更新后的张三和原来的李四
    assert len(updated_data) == 2
    # 找到张三的记录并验证数据已更新
    zhangsan_record = [record for record in updated_data if record[0] == '张三'][0]
    assert zhangsan_record[1] == 999.0
    print("7. Tested single record update.")

    # 8. 测试CSV导出
    export_result = db_test.export_to_csv("test_backup.csv")
    assert export_result == True
    print("8. Exported data to CSV file.")

    # 9. 清理
    del db_test # 关闭连接
    os.remove(test_db_file)
    print(f"9. Cleaned up and removed {test_db_file}.")
    print("--- Test Completed Successfully ---")
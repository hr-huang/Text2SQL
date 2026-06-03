"""生成电商数据库 — 13张表，模拟电商核心业务"""
import sqlite3, random
from datetime import datetime, timedelta
from faker import Faker

fake = Faker(["zh_CN", "en_US"])
DB = "data/ecommerce.db"
random.seed(42)
Faker.seed(42)

conn = sqlite3.connect(DB)
c = conn.cursor()

# ── 1. 商品分类 ──
c.execute("CREATE TABLE categories (category_id INTEGER PRIMARY KEY, name TEXT, parent_id INTEGER, description TEXT)")
categories = [
    (1,"电子产品",None,"手机、电脑、数码配件"),
    (2,"服装鞋帽",None,"男装、女装、鞋类"),
    (3,"食品饮料",None,"零食、饮料、生鲜"),
    (4,"图书音像",None,"图书、电子书、音乐"),
    (5,"手机通讯",None,"智能手机、功能机"),
    (6,"电脑办公",None,"笔记本、台式机、办公设备"),
    (7,"男装",None,"T恤、衬衫、裤装"),
    (8,"女装",None,"连衣裙、上衣、裙装"),
]
c.executemany("INSERT INTO categories VALUES(?,?,?,?)", categories)

# ── 2. 商品 ──
c.execute("""CREATE TABLE products (
    product_id INTEGER PRIMARY KEY, name TEXT, category_id INTEGER,
    unit_price REAL, cost REAL, unit TEXT, stock INTEGER, supplier_id INTEGER,
    FOREIGN KEY(category_id) REFERENCES categories(category_id))""")

products = []
for i in range(1, 201):
    cat = random.choice(categories)
    price = round(random.uniform(9.9, 9999.9), 2)
    products.append((i, fake.catch_phrase(), cat[0], price, round(price*0.4,2), "件", random.randint(0,500), random.randint(1,20)))
c.executemany("INSERT INTO products VALUES(?,?,?,?,?,?,?,?)", products)

# ── 3. 地区 ──
c.execute("CREATE TABLE regions (region_id INTEGER PRIMARY KEY, name TEXT)")
regions = [(1,"华北"),(2,"华东"),(3,"华南"),(4,"西南"),(5,"西北"),(6,"东北"),(7,"华中")]
c.executemany("INSERT INTO regions VALUES(?,?)", regions)

# ── 4. 客户 ──
c.execute("""CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY, name TEXT, gender TEXT, age INTEGER,
    city TEXT, province TEXT, region_id INTEGER,
    register_date TEXT, vip_level TEXT,
    FOREIGN KEY(region_id) REFERENCES regions(region_id))""")
customers = []
for i in range(1, 501):
    customers.append((i, fake.name(), random.choice(["男","女"]), random.randint(18,65),
        fake.city(), fake.province(), random.randint(1,7),
        fake.date_between("-3y","-1d").isoformat(), random.choice(["普通","银卡","金卡","钻石"])))
c.executemany("INSERT INTO customers VALUES(?,?,?,?,?,?,?,?,?)", customers)

# ── 5. 供应商 ──
c.execute("CREATE TABLE suppliers (supplier_id INTEGER PRIMARY KEY, name TEXT, contact TEXT, phone TEXT, city TEXT)")
suppliers = []
for i in range(1, 21):
    suppliers.append((i, fake.company(), fake.name(), fake.phone_number(), fake.city()))
c.executemany("INSERT INTO suppliers VALUES(?,?,?,?,?)", suppliers)

# ── 6. 员工 ──
c.execute("""CREATE TABLE employees (
    employee_id INTEGER PRIMARY KEY, name TEXT, department TEXT,
    title TEXT, hire_date TEXT, salary REAL, region_id INTEGER,
    FOREIGN KEY(region_id) REFERENCES regions(region_id))""")
departments = ["销售部","技术部","运营部","市场部","客服部","财务部","仓储部"]
titles = ["专员","主管","经理","总监"]
employees = []
for i in range(1, 51):
    employees.append((i, fake.name(), random.choice(departments), random.choice(titles),
        fake.date_between("-5y","-6m").isoformat(), round(random.uniform(5000,25000),0),
        random.randint(1,7)))
c.executemany("INSERT INTO employees VALUES(?,?,?,?,?,?,?)", employees)

# ── 7. 物流商 ──
c.execute("CREATE TABLE shippers (shipper_id INTEGER PRIMARY KEY, name TEXT, phone TEXT)")
shippers = [(1,"顺丰速运","95338"),(2,"京东物流","950616"),(3,"中通快递","95311"),(4,"圆通速递","95554"),(5,"韵达快递","95546")]
c.executemany("INSERT INTO shippers VALUES(?,?,?)", shippers)

# ── 8. 订单 ──
c.execute("""CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY, customer_id INTEGER, employee_id INTEGER,
    order_date TEXT, required_date TEXT, shipped_date TEXT,
    shipper_id INTEGER, status TEXT, total_amount REAL,
    FOREIGN KEY(customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY(employee_id) REFERENCES employees(employee_id),
    FOREIGN KEY(shipper_id) REFERENCES shippers(shipper_id))""")

orders = []
statuses = ["待付款","已付款","已发货","已完成","已取消","已退货"]
for i in range(1, 2001):
    order_date = fake.date_time_between("-2y","-1h")
    status = random.choices(statuses, weights=[10,20,15,40,10,5])[0]
    shipped = order_date + timedelta(hours=random.randint(2,72)) if status in ["已发货","已完成"] else None
    orders.append((i, random.randint(1,500), random.randint(1,50),
        order_date.isoformat(),
        (order_date+timedelta(days=random.randint(1,5))).isoformat(),
        shipped.isoformat() if shipped else None,
        random.randint(1,5), status, 0))  # total_amount 后面更新
c.executemany("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?)", orders)

# ── 9. 订单明细 ──
c.execute("""CREATE TABLE order_details (
    detail_id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER,
    unit_price REAL, quantity INTEGER, discount REAL,
    FOREIGN KEY(order_id) REFERENCES orders(order_id),
    FOREIGN KEY(product_id) REFERENCES products(product_id))""")

details = []
did = 0
for order_id in range(1, 2001):
    for _ in range(random.randint(1, 5)):
        did += 1
        pid = random.randint(1, 200)
        qty = random.randint(1, 10)
        price = [p[3] for p in products if p[0]==pid][0]
        details.append((did, order_id, pid, price, qty, round(random.random()*0.2, 2)))
c.executemany("INSERT INTO order_details VALUES(?,?,?,?,?,?)", details)

# 更新订单总金额
c.execute("""
    UPDATE orders SET total_amount = (
        SELECT ROUND(SUM(unit_price*quantity*(1-discount)), 2)
        FROM order_details WHERE order_details.order_id = orders.order_id
    )
""")

# ── 10. 支付记录 ──
c.execute("""CREATE TABLE payments (
    payment_id INTEGER PRIMARY KEY, order_id INTEGER, amount REAL,
    pay_method TEXT, pay_time TEXT, status TEXT,
    FOREIGN KEY(order_id) REFERENCES orders(order_id))""")

payments = []
methods = ["微信支付","支付宝","银行卡","信用卡","余额"]
for i in range(1, 2001):
    methods_used = random.sample(methods, random.randint(1,2))
    remaining = [t[0] for t in c.execute("SELECT total_amount FROM orders WHERE order_id=?",(i,)).fetchall()][0]
    for m in methods_used:
        amt = round(remaining * random.uniform(0.3, 1.0), 2) if len(methods_used)>1 else remaining
        payments.append((len(payments)+1, i, amt, m,
            fake.date_time_between("-2y","-1h").isoformat(),
            random.choice(["成功","成功","成功","成功","失败","退款"])))
c.executemany("INSERT INTO payments VALUES(?,?,?,?,?,?)", payments)

# ── 11. 评价 ──
c.execute("""CREATE TABLE reviews (
    review_id INTEGER PRIMARY KEY, product_id INTEGER, customer_id INTEGER,
    rating INTEGER, content TEXT, review_date TEXT,
    FOREIGN KEY(product_id) REFERENCES products(product_id),
    FOREIGN KEY(customer_id) REFERENCES customers(customer_id))""")

reviews = []
for i in range(1, 1001):
    reviews.append((i, random.randint(1,200), random.randint(1,500),
        random.choices([5,4,3,2,1], weights=[40,30,15,10,5])[0],
        fake.sentence(), fake.date_time_between("-2y","-1h").isoformat()))
c.executemany("INSERT INTO reviews VALUES(?,?,?,?,?,?)", reviews)

# ── 12. 库存日志 ──
c.execute("""CREATE TABLE inventory_log (
    log_id INTEGER PRIMARY KEY, product_id INTEGER, change_qty INTEGER,
    reason TEXT, log_time TEXT,
    FOREIGN KEY(product_id) REFERENCES products(product_id))""")

logs = []
reasons = ["采购入库","销售出库","退货入库","盘点调整","损耗报损"]
for i in range(1, 3001):
    logs.append((i, random.randint(1,200), random.randint(-50,100),
        random.choice(reasons), fake.date_time_between("-1y","-1h").isoformat()))
c.executemany("INSERT INTO inventory_log VALUES(?,?,?,?,?)", logs)

# ── 13. 营销活动 ──
c.execute("""CREATE TABLE campaigns (
    campaign_id INTEGER PRIMARY KEY, name TEXT, start_date TEXT, end_date TEXT,
    discount_type TEXT, discount_value REAL, budget REAL, status TEXT)""")

campaigns = []
camp_names = ["双11大促","618年中庆","年货节","开学季","国庆特惠","会员日","新用户专享","品牌日","清仓特卖","满减活动"]
for i, name in enumerate(camp_names, 1):
    start = fake.date_between("-1y","-1m")
    campaigns.append((i, name, start.isoformat(), (start+timedelta(days=random.randint(3,15))).isoformat(),
        random.choice(["满减","折扣","直降","买赠"]), round(random.uniform(0.5,0.95),2),
        round(random.uniform(5000,50000),0), random.choice(["进行中","已结束","已结束","已结束"])))
c.executemany("INSERT INTO campaigns VALUES(?,?,?,?,?,?,?,?)", campaigns)

# ── 14. 仓库 ──
c.execute("""CREATE TABLE warehouses (warehouse_id INTEGER PRIMARY KEY, name TEXT, city TEXT, province TEXT, capacity INTEGER)""")
c.executemany("INSERT INTO warehouses VALUES(?,?,?,?,?)", [(1,"华东仓(上海)","上海","上海",15000),(2,"华南仓(广州)","广州","广东",12000),(3,"华北仓(北京)","北京","北京",10000),(4,"西南仓(成都)","成都","四川",8000),(5,"华中仓(武汉)","武汉","湖北",9000)])

# ── 15. 仓库库存 ──
c.execute("""CREATE TABLE warehouse_inventory (wi_id INTEGER PRIMARY KEY, warehouse_id INTEGER, product_id INTEGER, quantity INTEGER, shelf_code TEXT, FOREIGN KEY(warehouse_id) REFERENCES warehouses(warehouse_id), FOREIGN KEY(product_id) REFERENCES products(product_id))""")
for _ in range(400):
    c.execute("INSERT INTO warehouse_inventory VALUES(?,?,?,?,?)", (None, random.randint(1,5), random.randint(1,200), random.randint(0,200), f"{chr(65+random.randint(0,5))}-{random.randint(1,50):02d}"))

# ── 16. 优惠券 ──
c.execute("""CREATE TABLE coupons (coupon_id INTEGER PRIMARY KEY, name TEXT, discount_type TEXT, discount_value REAL, min_amount REAL, total_qty INTEGER, used_qty INTEGER, start_date TEXT, end_date TEXT)""")
coupon_names = ["新人10元券","满200减30","全场8折","会员专享券","限时5折","满500减100","品牌满减","首单免邮","积分兑换券","节日特惠"]
for i, name in enumerate(coupon_names, 1):
    c.execute("INSERT INTO coupons VALUES(?,?,?,?,?,?,?,?,?)", (i, name, random.choice(["满减","折扣"]), round(random.uniform(0.5,0.95),2) if random.random()>0.5 else random.randint(5,100), random.randint(50,300), random.randint(100,500), random.randint(0,200), fake.date_between("-1y","-1m").isoformat(), fake.date_between("-15d","+30d").isoformat()))

# ── 17. 优惠券使用 ──
c.execute("""CREATE TABLE coupon_usage (usage_id INTEGER PRIMARY KEY, coupon_id INTEGER, order_id INTEGER, customer_id INTEGER, discount_amount REAL, FOREIGN KEY(coupon_id) REFERENCES coupons(coupon_id))""")
for i in range(1, 301):
    c.execute("INSERT INTO coupon_usage VALUES(?,?,?,?,?)", (i, random.randint(1,10), random.randint(1,2000), random.randint(1,500), round(random.uniform(5,100),2)))

# ── 18. 退货 ──
c.execute("""CREATE TABLE returns (return_id INTEGER PRIMARY KEY, order_id INTEGER, customer_id INTEGER, return_date TEXT, reason TEXT, refund_amount REAL, status TEXT, FOREIGN KEY(order_id) REFERENCES orders(order_id))""")
return_reasons = ["质量问题","尺寸不合适","与描述不符","不想要了","发错货","物流损坏"]
for i in range(1, 201):
    c.execute("INSERT INTO returns VALUES(?,?,?,?,?,?,?)", (i, random.randint(1,2000), random.randint(1,500), fake.date_time_between("-1y","-1h").isoformat(), random.choice(return_reasons), round(random.uniform(19,2000),2), random.choice(["待审核","已退款","已拒绝","已完成"])))

# ── 19. 退货明细 ──
c.execute("""CREATE TABLE return_details (rd_id INTEGER PRIMARY KEY, return_id INTEGER, product_id INTEGER, quantity INTEGER, unit_price REAL, FOREIGN KEY(return_id) REFERENCES returns(return_id))""")
for i in range(1, 401):
    c.execute("INSERT INTO return_details VALUES(?,?,?,?,?)", (i, random.randint(1,200), random.randint(1,200), random.randint(1,3), round(random.uniform(19,1000),2)))

# ── 20. 物流追踪 ──
c.execute("""CREATE TABLE shipping_tracking (track_id INTEGER PRIMARY KEY, order_id INTEGER, status TEXT, location TEXT, update_time TEXT, FOREIGN KEY(order_id) REFERENCES orders(order_id))""")
track_statuses = ["已揽收","运输中","到达中转","派送中","已签收"]
for i in range(1, 2001):
    if random.random()>0.3:
        c.execute("INSERT INTO shipping_tracking VALUES(?,?,?,?,?)", (None, i, random.choice(track_statuses), fake.city(), fake.date_time_between("-1y","-1h").isoformat()))

# ── 21. 客户地址 ──
c.execute("""CREATE TABLE customer_addresses (address_id INTEGER PRIMARY KEY, customer_id INTEGER, is_default INTEGER, receiver_name TEXT, phone TEXT, province TEXT, city TEXT, detail TEXT, zip TEXT, FOREIGN KEY(customer_id) REFERENCES customers(customer_id))""")
for i in range(1, 501):
    c.execute("INSERT INTO customer_addresses VALUES(?,?,?,?,?,?,?,?,?)", (i, i, 1, fake.name(), fake.phone_number(), fake.province(), fake.city(), fake.street_address(), fake.postcode()))

# ── 22. 商品属性 ──
c.execute("""CREATE TABLE product_attributes (attr_id INTEGER PRIMARY KEY, product_id INTEGER, attr_name TEXT, attr_value TEXT, FOREIGN KEY(product_id) REFERENCES products(product_id))""")
attr_types = ["颜色","尺寸","材质","重量","产地","适用人群"]
attr_values = {"颜色":["红","蓝","黑","白","灰"],"尺寸":["S","M","L","XL"],"材质":["棉","涤纶","真皮","不锈钢"],"重量":["0.5kg","1kg","2kg","5kg"],"产地":["浙江","广东","江苏","山东"],"适用人群":["成人","儿童","女性","男性"]}
for i in range(1, 301):
    at = random.choice(attr_types)
    c.execute("INSERT INTO product_attributes VALUES(?,?,?,?)", (i, random.randint(1,200), at, random.choice(attr_values[at])))

# ── 23. 购物车 ──
c.execute("""CREATE TABLE shopping_cart (cart_id INTEGER PRIMARY KEY, customer_id INTEGER, product_id INTEGER, quantity INTEGER, add_time TEXT, FOREIGN KEY(customer_id) REFERENCES customers(customer_id))""")
for i in range(1, 201):
    c.execute("INSERT INTO shopping_cart VALUES(?,?,?,?,?)", (i, random.randint(1,500), random.randint(1,200), random.randint(1,5), fake.date_time_between("-1m","-1h").isoformat()))

# ── 24. 搜索日志 ──
c.execute("""CREATE TABLE search_logs (search_id INTEGER PRIMARY KEY, customer_id INTEGER, keyword TEXT, result_count INTEGER, search_time TEXT)""")
keywords = ["手机","连衣裙","零食","笔记本","运动鞋","面膜","充电宝","耳机","T恤","牛奶","洗发水","蓝牙音箱"]
for i in range(1, 1001):
    c.execute("INSERT INTO search_logs VALUES(?,?,?,?,?)", (i, random.randint(1,500), random.choice(keywords), random.randint(3,150), fake.date_time_between("-1y","-1h").isoformat()))

# ── 25. 系统通知 ──
c.execute("""CREATE TABLE notifications (notify_id INTEGER PRIMARY KEY, customer_id INTEGER, title TEXT, content TEXT, is_read INTEGER, create_time TEXT)""")
notif_titles = ["订单发货通知","促销活动","优惠券到期提醒","物流更新","退款处理通知","评价邀请"]
for i in range(1, 1001):
    c.execute("INSERT INTO notifications VALUES(?,?,?,?,?,?)", (i, random.randint(1,500), random.choice(notif_titles), fake.sentence(), random.randint(0,1), fake.date_time_between("-1y","-1h").isoformat()))

# ── 26. 首页轮播 ──
c.execute("""CREATE TABLE banners (banner_id INTEGER PRIMARY KEY, title TEXT, image TEXT, link_url TEXT, sort_order INTEGER, is_active INTEGER)""")
banner_titles = ["双11狂欢节","618年中大促","新用户专享","品牌日特卖","限时秒杀","爆款推荐","开学季","数码专场"]
for i, title in enumerate(banner_titles, 1):
    c.execute("INSERT INTO banners VALUES(?,?,?,?,?,?)", (i, title, f"/images/banner_{i}.jpg", f"/promo/{i}", i, 1))

# ── 27. 商品图片 ──
c.execute("""CREATE TABLE product_images (image_id INTEGER PRIMARY KEY, product_id INTEGER, image_url TEXT, is_main INTEGER, sort_order INTEGER, FOREIGN KEY(product_id) REFERENCES products(product_id))""")
for i in range(1, 201):
    for j in range(random.randint(2,5)):
        c.execute("INSERT INTO product_images VALUES(?,?,?,?,?)", (None, i, f"/images/products/{i}_{j}.jpg", 1 if j==1 else 0, j))

# ── 索引 ──
for tbl, col in [("products","category_id"),("customers","region_id"),("orders","customer_id"),
    ("orders","order_date"),("order_details","order_id"),("payments","order_id"),
    ("reviews","product_id"),("reviews","rating"),("inventory_log","product_id"),
    ("warehouse_inventory","warehouse_id"),("warehouse_inventory","product_id"),
    ("coupon_usage","order_id"),("returns","order_id"),("return_details","return_id"),
    ("shipping_tracking","order_id"),("customer_addresses","customer_id"),
    ("product_attributes","product_id"),("shopping_cart","customer_id"),
    ("search_logs","customer_id"),("notifications","customer_id"),
    ("product_images","product_id")]:
    c.execute(f"CREATE INDEX IF NOT EXISTS idx_{tbl}_{col} ON {tbl}({col})")

conn.commit()
conn.close()
print(f"数据库已生成: {DB}")
print(f"27 张表: categories, products, customers, employees, suppliers, shippers, regions, orders, order_details, payments, reviews, inventory_log, campaigns, warehouses, warehouse_inventory, coupons, coupon_usage, returns, return_details, shipping_tracking, customer_addresses, product_attributes, shopping_cart, search_logs, notifications, banners, product_images")
print(f"200 商品 · 500 客户 · 2000 订单 · 1000 评价 · 50 员工 · 5 仓库 · 27 张表")

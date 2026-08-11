-- docker-compose MySQL 初始化：创建 5 个微服务独立数据库
-- 由 mysql 镜像 /docker-entrypoint-initdb.d/ 在首次启动时执行（幂等）
CREATE DATABASE IF NOT EXISTS lc_auth  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS lc_user  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS lc_chat  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS lc_kb    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS lc_admin CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

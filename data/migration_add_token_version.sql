-- ============================================================================
-- 迁移：为 users 表添加 token_version 列
-- ============================================================================
-- 用途：改密码时 token_version + 1，使所有旧 JWT token 失效
-- 执行方式：
--   mysql -u root -p rag_system < data/migration_add_token_version.sql
-- 兼容性：对已有行默认 0，与旧 token（无 ver 字段）的 get("ver", 0) 匹配
-- 幂等性：重复执行不会报错
-- ============================================================================

USE `rag_system`;

-- 使用存储过程实现幂等迁移（MySQL 不支持 ADD COLUMN IF NOT EXISTS）
DROP PROCEDURE IF EXISTS _add_token_version;

DELIMITER //
CREATE PROCEDURE _add_token_version()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = 'rag_system'
          AND TABLE_NAME = 'users'
          AND COLUMN_NAME = 'token_version'
    ) THEN
        ALTER TABLE `users`
            ADD COLUMN `token_version` INT NOT NULL DEFAULT 0
            COMMENT 'Token 版本号（改密码时+1，使旧 token 失效）'
            AFTER `is_active`;
    END IF;
END //
DELIMITER ;

CALL _add_token_version();
DROP PROCEDURE IF EXISTS _add_token_version;

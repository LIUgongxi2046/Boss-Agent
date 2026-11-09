from uuid import UUID


def slice_name(run_id, epoch):
    if not isinstance(run_id, str) or str(UUID(run_id)) != run_id or type(epoch) is not int or epoch <= 0:
        raise ValueError("客体 slice 运行身份无效")
    return "bossrun" + UUID(run_id).hex + "e" + str(epoch) + ".slice"


def work_group(run_id, epoch):
    return "/" + slice_name(run_id, epoch) + "/boss-" + run_id + "-" + str(epoch) + ".service"

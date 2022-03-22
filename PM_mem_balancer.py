import requests
import urllib3
import time

MAXIMUM_HOST_LOAD = 0.849

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

while True:
    cluster_dict: dict = {}
    cluster_vm: dict = {}
    cluster = []
    cl_max_mem: int = 0
    cl_mem: int = 0

    server = "https://10.10.10.10:8006"
    payload = {'username': "root@pam", 'password': "YourPassword"}
    url = f'{server}/api2/json/access/ticket'
    get_token = requests.post(url, data=payload, verify=False)
    if not get_token.ok: raise 'Неверные авторизационные данные'
    print(f'Успешная авторизация. Код ответа - {get_token.status_code}')
    ticket = (get_token.json()['data']['ticket'])
    token = (get_token.json()['data']['CSRFPreventionToken'])

    payload = {'PVEAuthCookie': ticket}
    header = {'CSRFPreventionToken': token}
    url = f'{server}/api2/json/nodes'
    hosts_request = requests.get(url, cookies=payload, verify=False)
    temp = (hosts_request.json()['data'])

    for _ in temp:
        if _["status"] == "online":
            cl_max_mem += int(_["maxmem"])
            cl_mem += int(_["mem"])
            cluster_dict[_["node"]] = int(_["maxmem"]), int(_["mem"])
    cluster_dict = dict(sorted(cluster_dict.items(), key=lambda x: x[0]))
    cluster_load: float = cl_mem / cl_max_mem  # Загрузка кластера
    if cluster_load > 1:
        raise f"Загрузка кластера не может быть больше 1, а тут {cluster_load}!"
    print(f'Общая ОЗУ кластера = {round(cl_max_mem / 1024 ** 3)} GB')
    print(f'Занятая ОЗУ кластера = {int(cl_mem / 1024 ** 3)} GB')
    print(f'Средняя загрузка кластера = {round(cl_mem / cl_max_mem * 100, 2)} %')
    # print("Кластер -", cluster_dict)

    url = f'{server}/api2/json/cluster/resources'
    hosts_resources_request = requests.get(url, cookies=payload,
                                           verify=False)
    temp = (hosts_resources_request.json()['data'])

    for host in cluster_dict:
        for vm in temp:
            if vm["type"] == "qemu" and vm["status"] == "running":
                if host == vm["node"]:
                    cluster_vm[int(vm["vmid"])] = int(vm["mem"]), vm["node"]


    class Host:
        def __init__(self, host_mem: int, host_used_mem: int, name: str):
            self.over = 0
            self.name = name
            self.memory = host_mem
            self.load = host_used_mem
            self.threshold_mem = int(host_mem * MAXIMUM_HOST_LOAD - host_used_mem)
            self.vm_list = self.local_vm()
            self.overload = self.overload_calculate()
            self.show()

        def local_vm(self):
            """Определяем перечень VM, работающих на данном хосте"""
            vm_list = {}
            for vm in cluster_vm.items():
                if self.name == vm[1][1]:
                    vm_list[vm[0]] = vm[1][0]
            return vm_list

        def overload_calculate(self):
            """Высчитываем перегруженность/недогруженность хоста"""
            self.over = self.load / self.memory - cluster_load
            return self.over

        def host_overload_return(self):
            """Возвращаем коэффициент загруженности сервера"""
            return int(self.overload * self.memory)

        def vm_present(self):
            """Возвращаем словарь с VM, предложенных для миграции в случае перегруженности хоста.
            Но при определённых условиях словарь может оказаться пустым (самая маленькая VM > размера
            перегруженности хоста."""
            migrate_vm = dict(
                filter(lambda item: item[1] < self.load - cluster_load * self.memory, self.vm_list.items()))
            if not migrate_vm and self.overload > cluster_load * 1.025:  # Если перегруженный хост не предлагает VM
                temp_vm_dict = self.vm_list
            else:
                temp_vm_dict = migrate_vm.copy()
            for vm in temp_vm_dict:
                url = f'{server}/api2/json/nodes/{self.name}/qemu/{vm}/migrate'
                check_request = requests.get(url, cookies=payload, verify=False)
                local_disk = (check_request.json()['data']['local_disks'])
                if local_disk:
                    print(f'{vm} содержит {local_disk}')
                    del migrate_vm[vm]
            return migrate_vm

        def show(self):
            print('*************************************************')
            print(f'Хост -', self.name)
            print(f'Общая ОЗУ хоста - {round(self.memory / 1024 ** 3)} GB')
            print(f'Занятая ОЗУ хоста - {int(self.load / 1024 ** 3)} GB')
            print(f'Загрузка хоста - {round(self.load / self.memory * 100, 2)}%')
            print(f'Перегруженность хоста - ({round(self.overload * 100, 2)}%)')
            print(f'Размер избыточной загрузки ОЗУ: {round(self.host_overload_return() / 1024 ** 3, 2)} GB')
            print(f'Может вместить без ущерба: {round(self.threshold_mem / 1024 ** 3, 2)} GB')
            print(f'Список виртуальных машин:')
            print([f'{key}:{round(values / 1024 ** 3, 1)} GB' for key, values in self.vm_list.items()])
            print(f'Список виртуальных машин для миграции:')
            print([f'{key}:{round(values / 1024 ** 3, 1)} GB' for key, values in self.vm_present().items()])


    """Создаём хосты подставляя данные из парсинга и список (cluster) из хостов"""
    for host, mem in cluster_dict.items():
        host = Host(mem[0], mem[1], str(host))
        cluster.append(host)


    def hosts_selection():
        """Выбираем хост-донор и хост-реципиент"""
        cl_overload_mem = {}
        host_donor = None
        for host in cluster:
            cl_overload_mem[host] = host.host_overload_return()
        donors = {}
        recipients = []
        for host in cluster:
            if host.vm_present():
                print(f'Донор: {host.name}: ', end="")
                print([f'{key}:{round(values / 1024 ** 3, 2)} GB' for key, values in host.vm_present().items()])
                donors[host] = host.host_overload_return()
            else:
                recipients.append(host)
        try:
            host_donor = max(donors, key=donors.get)
        except ValueError:
            print(' ======================================')
            print('| Нечего балансировать / Nothing to do |')
            print(' ======================================')
            exit(0)
        host_recipient = min(cl_overload_mem, key=cl_overload_mem.get)
        print(f'Донор: {host_donor.name}. Реципиент: {host_recipient.name}')
        return host_donor, host_recipient


    def vm_select(donor, recipient):
        """Выбираем VM для миграции с самого загруженного сервера, готового отдать их"""
        vm_dict = dict(filter(lambda item: item[1] < recipient.threshold_mem, donor.vm_present().items()))
        if vm_dict:
            vm_with_maxmem = max(vm_dict, key=vm_dict.get)
        else:
            print(' =========================================')
            print('| Нечего мигрировать / Nothing to migrate |')
            print(' =========================================')
            exit(0)
        vm_mem = vm_dict[vm_with_maxmem]
        print(f'{donor.name} отправляет VM-{vm_with_maxmem}: {round(vm_mem / 1024 ** 3, 2)} GB на {recipient.name}')
        return donor.name, recipient.name, vm_with_maxmem


    def vm_migration(donor, recipient, vm):
        options = {'target': recipient, 'online': 1}
        url = f'{server}/api2/json/nodes/{donor}/qemu/{vm}/migrate'
        job = requests.post(url, cookies=payload, headers=header, data=options, verify=False)
        print(f'Запрос на миграцию - {job.status_code}')
        if not job.ok: raise 'Запрос на миграцию не прошёл'
        pid = job.json()["data"]
        print(f'Номер задания: {pid}')
        status = True
        timer: int = 0
        while status:
            timer += 10
            time.sleep(10)
            url = f'{server}/api2/json/nodes/{recipient}/qemu'
            request = requests.get(url, cookies=payload, verify=False)
            running_vms = request.json()['data']
            for _ in running_vms:
                if _['vmid'] == vm and _['status'] == 'running':
                    print(f'{pid} - Завершена!')
                    status = False
                    break
                elif _['vmid'] == vm and _['status'] != 'running':
                    print(f'Что-то пошло не так. STATUS = {_["status"]}')
                    exit(1)
            else:
                print(f'Миграция VM: {vm}... {timer} sec.')


    vm_migration(*vm_select(*hosts_selection()))
    print(f'Ждём 10 секунд обновления информации кластера')
    print(f'Waiting for cluster information update')
    time.sleep(10)

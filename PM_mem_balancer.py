import requests
import urllib3
import time

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
    print(get_token.status_code)
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
    print("Кластер -", cluster_dict)

    url = f'{server}/api2/json/cluster/resources'
    hosts_resources_request = requests.get(url, cookies=payload,
                                           verify=False)  # TODO изменить запрос на вывод только VM
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
            self.vm_list = self.local_vm()
            self.overload = self.overload_calculate()
            self.show()
            # self.vm_present()  # If no self.show - delete #

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
            iteration = len(migrate_vm)
            for _ in range(iteration):  # Проверяем VM на наличие локальных дисков/CD-ROM
                vm_check = max(migrate_vm, key=migrate_vm.get)
                request = f'{server}/api2/json/nodes/{self.name}/qemu/{vm_check}/migrate'
                check_request = requests.get(request, cookies=payload, verify=False)
                local_disk = (check_request.json()['data']['local_disks'])
                if local_disk:
                    print(local_disk)
                    del migrate_vm[vm_check]
            return migrate_vm

        def show(self):
            print('*************************************************')
            print(f'Хост -', self.name)
            print(f'Общая ОЗУ хоста - {round(self.memory / 1024 ** 3)} GB')
            print(f'Занятая ОЗУ хоста - {int(self.load / 1024 ** 3)} GB')
            print(f'Загрузка хоста - {round(self.load / self.memory * 100, 2)}%')
            print(f'Перегруженность хоста - ({round(self.overload * 100, 2)}%)')
            print(f'Размер избыточной загрузки ОЗУ: {round(self.host_overload_return() / 1024 ** 3, 2)} GB')
            print(f'Список виртуальных машин:')
            print(self.vm_list)
            print(f'Список виртуальных машин для миграции:')
            print(self.vm_present())


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
                print(f'Донор: {host.name}: {host.vm_present()}')
                donors[host] = host.host_overload_return()
            else:
                recipients.append(host)
        print(f'ДОНОРЫ: {donors}')
        try:
            host_donor = max(donors, key=donors.get)
        except ValueError:
            print(' ====================================')
            print('| Нечего балансировать / Nothing to do |')
            print(' ====================================')
            exit(0)
        host_recipient = min(cl_overload_mem, key=cl_overload_mem.get)
        print(f'Донор: {host_donor.name}. Реципиент: {host_recipient.name}')
        return host_donor, host_recipient


    def vm_select(donor, recipient):
        """Выбираем VM для миграции с самого загруженного сервера, готового отдать их"""
        vm_dict = dict(filter(lambda item: item[1] < abs(recipient.host_overload_return()), donor.vm_present().items()))
        print(f'VM_DICT: {vm_dict}')
        if vm_dict:
            vm = max(vm_dict, key=vm_dict.get)
        else:
            print(' =========================================')
            print('| Нечего мигрировать / Nothing to migrate |')
            print(' =========================================')
            exit(0)
        vm_mem = vm_dict[vm]
        print(f'{donor.name} отправляет VM-{vm}: {round(vm_mem / 1024 ** 3, 2)} GB на {recipient.name}')
        return donor.name, recipient.name, vm


    def vm_migration(donor, recipient, vm):
        options = {'target': recipient, 'online': 1}
        url = f'{server}/api2/json/nodes/{donor}/qemu/{vm}/migrate'
        job = requests.post(url, cookies=payload, headers=header, data=options, verify=False)
        print(job.status_code)
        pid = job.json()['data']
        status = True
        while status:
            time.sleep(10)
            url = f'{server}/api2/json/cluster/tasks'
            request = requests.get(url, cookies=payload, verify=False)
            print(request.status_code)
            tasks = request.json()['data']
            for task in tasks:
                if task['upid'] == pid:
                    print(f'UPID: {pid}')
                    print(f"PID: {task.get('pid')}")
                    print(f'STATUS: {task.get("status")}')
                    print("**************************")
            for task in tasks:
                if task['upid'] == pid and task.get('status') == 'OK':
                    print(f'{pid} - Завершена!')
                    status = False
                    break
                elif task['upid'] == pid and not task.get('pid'):
                    print('Миграция')
                    break


    vm_migration(*vm_select(*hosts_selection()))

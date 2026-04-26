async function loadDashboard() {
    try {
        
        const response = await fetch('./data.json'); 
        const data = await response.json();

        const ultimaAtualizacao = data.ultima_atualizacao; // "26/04/2026 04:02"

        const partes = ultimaAtualizacao.match(/(\d+)\/(\d+)\/(\d+) (\d+):(\d+)/);
        
        const dataISO = `${partes[3]}-${partes[2]}-${partes[1]}T${partes[4]}:${partes[5]}:00-03:00`;
        const dataAtual = new Date(dataISO);
        const agora = new Date();
        const horasPassadas = Math.floor((agora - dataAtual) / 3600000);

        let corAviso, textoAviso;
        if (horasPassadas < 12) {
            corAviso = '#3fb950';
            textoAviso = `✅ Atualizado há ${horasPassadas}h`;
        } else if (horasPassadas < 24) {
            corAviso = '#d29922';
            textoAviso = `⚠️ Atualizado há ${horasPassadas}h — dados podem estar desatualizados`;
        } else {
            corAviso = '#f85149';
            textoAviso = `🔴 Atualizado há ${horasPassadas}h — robô pode estar com problema!`;
        }

        const spanUpdate = document.getElementById('update-time');
        spanUpdate.innerText = `${ultimaAtualizacao} · ${textoAviso}`;
        spanUpdate.style.color = corAviso;
        
        const grid = document.getElementById('dashboard-grid');
        grid.innerHTML = ''; 

        data.ativos.forEach(ativo => {
            const isUp = parseFloat(ativo.variacao) > 0;
            const card = document.createElement('div');
            card.className = 'card';
            
            card.innerHTML = `
                <div class="card-header">
                    <h2>${ativo.moeda}</h2>
                    <span>${ativo.emoji}</span>
                </div>
                <div class="price">$ ${ativo.preco}</div>
                <div class="variation ${isUp ? 'up' : 'down'}">
                    ${isUp ? '▲' : '▼'} ${ativo.variacao}% (Est. p/ amanhã)
                </div>
                <p>Status: <strong>${ativo.status}</strong></p>
                <a href="./${ativo.imagem}" target="_blank" class="chart-btn">Ver Gráfico de IA</a>
            `;
            grid.appendChild(card);
        });
    } catch (error) {
        console.error("Erro ao carregar dados:", error);
        document.getElementById('dashboard-grid').innerHTML = "<p>Dados ainda não disponíveis. O robô precisa rodar uma vez!</p>";
    }
}

window.onload = loadDashboard;
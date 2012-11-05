<!DOCTYPE HTML>
<html>
<head>
    <title>{{ monthName }}'s transactions</title>
    
    <link type="text/css" rel="stylesheet" href="./jquery.jqplot.min.css">


    <script type="text/javascript" src="./jquery.min.js"></script>
    <script type="text/javascript" src="./jquery.jqplot.min.js"></script>
    <script type="text/javascript" src="./plugins/jqplot.dateAxisRenderer.min.js"></script>
    <script type="text/javascript" src="./plugins/jqplot.logAxisRenderer.min.js"></script>
    <script type="text/javascript" src="./plugins/jqplot.canvasTextRenderer.js"></script>
    <script type="text/javascript" src="./plugins/jqplot.canvasAxisTickRenderer.js"></script>
    <script type="text/javascript" src="./plugins/jqplot.cursor.min.js"></script>
    <script type="text/javascript" src="./plugins/jqplot.highlighter.min.js"></script>
    <!--script type="text/javascript" src="./plugins/jqplot.trendline.min.js"></script-->
    
    
</head>
<body>
    <div id="chart" style="height:680px; width:100%;"></div>
    
    <script type="text/javascript">
    $(document).ready(function(){
        $.jqplot.config.enablePlugins = true;
        var trans = [{% for item in transactions %}['{{ item.datetime }}', {{ item.amount }}]{% if not loop.last %},{% endif %}{% endfor %}];
        var balan = [{% for item in transactions %}['{{ item.datetime }}', {{ item.balance }}]{% if not loop.last %},{% endif %}{% endfor %}];

        var plot1 = $.jqplot('chart', [balan, trans], {
          title:'{{ monthName }}\'s transactions',
          seriesDefaults: {showMarker:false},
          series: [
              {fill: true, label: 'Balance'},
              {yaxis: 'y2axis', label: 'Transactions'}
          ],
          legend: {
          	show: true,
          	placement: 'outsideGrid'
          },
          axesDefaults: {
              useSeriesColor: true,
              rendererOptions: {
                alignTicks: true
              }
          },
          animate: !$.jqplot.use_excanvas,
          axes:{
            xaxis:{
              pad: 0,
              renderer:$.jqplot.DateAxisRenderer,
              rendererOptions:{
                  tickRenderer:$.jqplot.CanvasAxisTickRenderer
              },
              tickOptions:{
                  formatString:'%Y-%m-%d',
                  fontSize:'10pt', 
                  fontFamily:'Tahoma',
                  angle: -40
              },
              min: '{{ minDate }}', 
              tickInterval:'6 days',
              drawMajorGridlines: false
            },
            yaxis:{
              renderer: $.jqplot.LogAxisRenderer,
              rendererOptions:{
                minorTicks: 1
              },
              tickOptions:{
                  formatString: "ISK %'d",
                  showMark: false
              }
            },
            y2axis: {
              tickOptions:{
                  formatString: "ISK %'.2f",
              }
            }
          },
          
          highlighter: {
              show: true,
              sizeAdjust: 7.5
          },
          cursor:{
              show: true,
              
              zoom: true,
              looseZoom: true
          }
        });
    });
        
    </script>
</body>
</html>